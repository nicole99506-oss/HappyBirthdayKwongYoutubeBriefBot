"""Minimal YouTube-to-Telegram digest runner.

Each workflow run handles at most one video. Only the summary is sent to Telegram;
no mind maps, summary archive, Google Drive sync, or reading site are generated.
"""
import sys
import traceback
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import commands, config, worker_sync
from . import state as state_mod
from . import summarizer, telegram_api as tg, youtube


def enqueue_new_uploads(st: dict) -> int:
    added = 0
    queued_ids = {q["video_id"] for q in st["queue"]}
    for cid, ch in st["channels"].items():
        # In Worker mode, do not queue videos until the channel's add-time
        # initialization succeeds. This prevents old RSS entries from slipping
        # into the queue if D1 synchronization or initialization temporarily fails.
        if config.BOT_WORKER_URL and not ch.get("worker_initialized", False):
            continue
        try:
            latest = youtube.latest_from_rss(cid)
        except Exception as e:
            print(f"[rss] {ch['title']}: {e}")
            continue
        for video in latest:
            if video["video_id"] in ch["seen"] or video["video_id"] in queued_ids:
                continue
            video["channel_id"] = cid
            st["queue"].append(video)
            queued_ids.add(video["video_id"])
            added += 1
    return added


def _today() -> str:
    return datetime.now(ZoneInfo(config.TIMEZONE)).strftime("%Y-%m-%d")


def process_queue(st: dict) -> None:
    """Process one video per run and respect the configured request cooldown."""
    if st.get("gemini_pause_date") == _today():
        print("[gemini] paused for today after a quota/rate-limit response")
        return
    if not st["queue"]:
        return
    if config.FREE_MODE and state_mod.daily_remaining(st) <= 0:
        print("[cap] daily summary cap reached; keeping the remaining queue")
        return

    now = datetime.now(ZoneInfo("UTC"))
    last_attempt = st.get("last_gemini_attempt_at")
    if last_attempt:
        try:
            last_dt = datetime.fromisoformat(last_attempt)
            if now - last_dt < timedelta(hours=config.MIN_HOURS_BETWEEN_GEMINI_REQUESTS):
                print("[gemini] cooldown active; waiting before the next request")
                return
        except (TypeError, ValueError):
            print("[gemini] could not parse last attempt timestamp; proceeding once")

    item = st["queue"][0]
    cid = item["channel_id"]
    ch = st["channels"].get(cid)
    if ch is None:
        st["queue"].pop(0)
        return

    # Persist the attempt time before calling Gemini. Even failed non-429 requests
    # will not be retried on the next hourly workflow run.
    st["last_gemini_attempt_at"] = now.isoformat()
    try:
        data = summarizer.summarize_video(item["url"])
    except summarizer.QuotaExhausted as e:
        # Avoid repeated 429s: do not call Gemini again until the next local day.
        st["gemini_pause_date"] = _today()
        print(f"[gemini] quota/rate limit reached; pausing until tomorrow: {e}")
        if st.get("last_quota_notice_date") != _today():
            try:
                tg.send_message(
                    config.TELEGRAM_CHAT_ID,
                    "⏸️ Gemini 回報配額／請求頻率限制。為避免連續觸發限制，"
                    "我會暫停摘要生成，明天再自動嘗試；待處理影片會保留。",
                    markdown=False,
                )
                st["last_quota_notice_date"] = _today()
            except Exception as notify_error:
                print(f"[notify] {notify_error}")
        return
    except Exception as e:
        # One attempt only. Keep this video queued and wait until the next scheduled run.
        print(f"[summarize] {item['video_id']} failed; leaving it queued: {e}")
        traceback.print_exc()
        return

    # Only mark a video as seen after Gemini successfully generated its summary.
    try:
        tg.send_message(
            config.TELEGRAM_CHAT_ID,
            summarizer.summary_to_telegram(item, ch["title"], data),
        )
    except Exception as e:
        # Keep it queued so a Telegram delivery failure does not silently lose the digest.
        print(f"[telegram] send failed; leaving video queued for next run: {e}")
        return

    st["queue"].pop(0)
    ch["seen"].append(item["video_id"])
    state_mod.record_summary(st)
    print(f"[summary] delivered {item['video_id']} — {item['title']}")


def main() -> int:
    missing = [
        name for name, value in [
            ("TELEGRAM_BOT_TOKEN", config.TELEGRAM_BOT_TOKEN),
            ("TELEGRAM_CHAT_ID", config.TELEGRAM_CHAT_ID),
            ("GEMINI_API_KEY", config.GEMINI_API_KEY),
            ("YOUTUBE_API_KEY", config.YOUTUBE_API_KEY),
        ] if not value
    ]
    if missing:
        print("Missing required secrets:", ", ".join(missing))
        return 1

    st = state_mod.load()
    if not st.get("greeted"):
        try:
            tg.send_message(
                config.TELEGRAM_CHAT_ID,
                "🎂 *Happy Birthday Kwong* 已啟動！\n\n"
                "用 /add @頻道名稱 加入 YouTube 頻道，/help 查看指令。",
            )
            st["greeted"] = True
        except Exception as e:
            print(f"[greet] {e}")

    try:
        if config.BOT_WORKER_URL:
            worker_sync.sync_remote_channels(st)
        else:
            # Keep the existing polling path until the Cloudflare Worker is configured.
            commands.process_updates(st)
    except Exception as e:
        print(f"[commands/worker-sync] {e}")
        traceback.print_exc()

    enqueue_new_uploads(st)
    process_queue(st)

    st["last_run"] = datetime.now(ZoneInfo("UTC")).isoformat()
    state_mod.save(st)
    try:
        worker_sync.publish_status(st)
    except Exception as e:
        print(f"[worker-status] {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
