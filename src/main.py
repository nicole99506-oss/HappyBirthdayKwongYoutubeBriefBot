"""Orchestrator — one run of the hourly GitHub Actions job.

Order of operations:
  1. Handle Telegram commands (add/remove channels, backfill choices)
  2. Poll RSS feeds for new uploads -> enqueue
  3. Process the queue (respecting free-tier caps):
       summarize -> Telegram -> mind map update + send -> Drive sync
  4. Rebuild the reading site
"""
import json
import os
import sys
import traceback
from datetime import datetime, timezone

from . import commands, config, drive_sync, mindmap, site
from . import state as state_mod
from . import summarizer, telegram_api as tg, youtube


def enqueue_new_uploads(st: dict) -> int:
    added = 0
    for cid, ch in st["channels"].items():
        try:
            latest = youtube.latest_from_rss(cid)
        except Exception as e:
            print(f"[rss] {ch['title']}: {e}")
            continue
        queued_ids = {q["video_id"] for q in st["queue"]}
        for v in latest:
            if v["video_id"] in ch["seen"] or v["video_id"] in queued_ids:
                continue
            v["channel_id"] = cid
            st["queue"].append(v)
            added += 1
    return added


def _summary_json_path(cid: str, vid: str) -> str:
    d = os.path.join(config.SUMMARY_DIR, cid)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"{vid}.json")




def _notify_error_once(st: dict, err: Exception) -> None:
    """Telegram-notify about summarization errors at most once per day."""
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if st.get("last_error_notified") == today:
        return
    st["last_error_notified"] = today
    try:
        tg.send_message(config.TELEGRAM_CHAT_ID,
                        "⚠️ Summaries are failing and will be retried automatically. "
                        f"Latest error: {str(err)[:300]}\n\n"
                        "If this repeats, check the Actions log — a likely fix is "
                        "setting the GEMINI_MODEL repository variable to a current "
                        "model name.", markdown=False)
    except Exception as e2:
        print(f"[notify] {e2}")




def process_queue(st: dict) -> None:
    budget_run = config.MAX_VIDEOS_PER_RUN
    processed = 0
    while st["queue"] and processed < budget_run:
        if state_mod.daily_remaining(st) <= 0:
            print("[cap] daily free-tier cap reached; deferring rest of queue")
            break
        item = st["queue"][0]
        cid = item["channel_id"]
        ch = st["channels"].get(cid)
        if ch is None:  # channel removed while queued
            st["queue"].pop(0)
            continue
        try:
            data = summarizer.summarize_video(item["url"])
        except summarizer.QuotaExhausted:
            tg.send_message(config.TELEGRAM_CHAT_ID,
                            "⏳ Gemini free-tier quota reached for today. "
                            f"{len(st['queue'])} video(s) will be digested on the next "
                            "runs — no charges are ever incurred.", markdown=False)
            break
        except Exception as e:
            print(f"[summarize] {item['video_id']}: {e}")
            traceback.print_exc()
            # Keep the video in the queue and retry on later runs; only give up
            # after 3 failed attempts. Stop this run entirely so one systemic
            # failure (e.g. a retired model name) can never burn the queue.
            item["fails"] = item.get("fails", 0) + 1
            if item["fails"] >= 3:
                print(f"[summarize] giving up on {item['video_id']} after 3 attempts")
                ch["seen"].append(item["video_id"])
                st["queue"].pop(0)
                continue
            _notify_error_once(st, e)
            break

        st["queue"].pop(0)
        ch["seen"].append(item["video_id"])
        state_mod.record_summary(st)
        processed += 1

        md = summarizer.summary_to_markdown(item, ch["title"], data)
        with open(_summary_json_path(cid, item["video_id"]), "w", encoding="utf-8") as f:
            json.dump({"video_id": item["video_id"], "title": item["title"],
                       "published": item["published"], "url": item["url"],
                       "data": data, "markdown": md}, f, ensure_ascii=False, indent=2)

        # 1) Telegram text
        try:
            tg.send_message(config.TELEGRAM_CHAT_ID,
                            summarizer.summary_to_telegram(item, ch["title"], data))
        except Exception as e:
            print(f"[telegram] {e}")

        # 2) Mind map update + send
        try:
            tree = summarizer.merge_into_tree(ch["title"], mindmap.load_tree(cid), data)
            mindmap.save_tree(cid, tree)
            png = mindmap.render(cid, tree)
            tg.send_photo(config.TELEGRAM_CHAT_ID, png,
                          caption=f"🧠 {ch['title']} — knowledge map updated")
        except summarizer.QuotaExhausted:
            print("[mindmap] quota reached; map will refresh on a later video")
        except Exception as e:
            print(f"[mindmap] {e}")

        # 3) Drive sync
        if drive_sync.enabled():
            try:
                entries = _all_entries(cid)
                latest = entries[-1] if entries else None
                drive_sync.sync_channel(ch["title"], entries, latest)
            except Exception as e:
                print(f"[drive] {e}")


def _all_entries(cid: str) -> list[dict]:
    d = os.path.join(config.SUMMARY_DIR, cid)
    out = []
    if os.path.isdir(d):
        for fn in os.listdir(d):
            if fn.endswith(".json"):
                with open(os.path.join(d, fn), "r", encoding="utf-8") as f:
                    out.append(json.load(f))
    out.sort(key=lambda e: e["published"])
    return out


def main() -> int:
    missing = [n for n, v in [("TELEGRAM_BOT_TOKEN", config.TELEGRAM_BOT_TOKEN),
                              ("TELEGRAM_CHAT_ID", config.TELEGRAM_CHAT_ID),
                              ("GEMINI_API_KEY", config.GEMINI_API_KEY),
                              ("YOUTUBE_API_KEY", config.YOUTUBE_API_KEY)] if not v]
    if missing:
        print("Missing required secrets:", ", ".join(missing))
        return 1

    st = state_mod.load()

    if not st.get("greeted"):
        try:
            tg.send_message(config.TELEGRAM_CHAT_ID,
                            "🎂 *Happy Birthday Kwong* is alive!\n\n"
                            "Add your first channel with /add @handle — "
                            "try /help for everything I can do.")
            st["greeted"] = True
        except Exception as e:
            print(f"[greet] {e}")

    try:
        commands.process_updates(st)
    except Exception as e:
        print(f"[commands] {e}")
        traceback.print_exc()

    enqueue_new_uploads(st)
    process_queue(st)

    if drive_sync.enabled():
        try:
            drive_sync.sync_start_here()
        except Exception as e:
            print(f"[drive start-here] {e}")
        if st.pop("drive_full_sync", False):
            done = 0
            for cid, ch in st["channels"].items():
                try:
                    entries = _all_entries(cid)
                    if entries:
                        drive_sync.sync_channel_full(ch["title"], entries)
                        done += len(entries)
                except Exception as e:
                    print(f"[drive full-sync] {ch['title']}: {e}")
            try:
                tg.send_message(config.TELEGRAM_CHAT_ID,
                                f"✅ Drive sync complete — {done} briefing(s) uploaded.",
                                markdown=False)
            except Exception as e:
                print(f"[drive full-sync notify] {e}")

    if st.pop("rebuild_maps", False):
        for cid, ch in st["channels"].items():
            try:
                entries = _all_entries(cid)
                if not entries:
                    continue
                tree = summarizer.build_tree_from_scratch(ch["title"], entries)
                if tree:
                    mindmap.save_tree(cid, tree)
                    png = mindmap.render(cid, tree)
                    tg.send_photo(config.TELEGRAM_CHAT_ID, png,
                                  caption=f"🧠 {ch['title']} — knowledge map rebuilt "
                                          f"from {len(entries)} briefings")
            except summarizer.QuotaExhausted:
                print("[rebuildmap] quota reached")
                break
            except Exception as e:
                print(f"[rebuildmap] {ch['title']}: {e}")

    try:
        site.build(st)
    except Exception as e:
        print(f"[site] {e}")
        traceback.print_exc()

    st.setdefault("last_run", "")
    st["last_run"] = datetime.now(timezone.utc).isoformat()
    state_mod.save(st)
    return 0


if __name__ == "__main__":
    sys.exit(main())
