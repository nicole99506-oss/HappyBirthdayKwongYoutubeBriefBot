"""Minimal YouTube-to-Telegram digest runner.

Each workflow run handles at most one ready video. Failed items stay in the
queue with retry metadata, and a generated summary is cached until Telegram
delivery succeeds so Gemini usage is not wasted on Telegram send failures.
"""
import sys
import traceback
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import commands, config, worker_sync
from . import state as state_mod
from . import summarizer, telegram_api as tg, youtube


# Backoff for a video that fails summarization: 1 hour, 6 hours, 1 day,
# then park it for 7 days. The item is never deleted automatically.
RETRY_DELAYS = (timedelta(hours=1), timedelta(hours=6), timedelta(days=1), timedelta(days=7))


def enqueue_new_uploads(st: dict) -> int:
    added = 0
    queued_ids = {q["video_id"] for q in st["queue"]}
    for cid, ch in st["channels"].items():
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


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=ZoneInfo("UTC"))
        return parsed.astimezone(ZoneInfo("UTC"))
    except (TypeError, ValueError):
        return None


def _schedule_retry(item: dict, error: Exception) -> None:
    attempts = int(item.get("summary_attempts", 0)) + 1
    item["summary_attempts"] = attempts
    item["last_summary_error"] = str(error)[:1000]
    delay = RETRY_DELAYS[min(attempts - 1, len(RETRY_DELAYS) - 1)]
    item["next_retry_at"] = (datetime.now(ZoneInfo("UTC")) + delay).isoformat()
    print(
        f"[queue] {item.get('video_id')} summary attempt {attempts} failed; "
        f"retry scheduled in {delay}: {error}"
    )


def process_queue(st: dict) -> None:
    """Process one ready video, preserving failed items and cached summaries."""
    if st.get("gemini_pause_date") == _today() and not any(
        queued.get("summary_data") for queued in st.get("queue", [])
    ):
        print("[gemini] paused for today after a quota/rate-limit response")
        return
    if not st["queue"]:
        return
    if config.FREE_MODE and state_mod.daily_remaining(st) <= 0:
        print("[cap] daily summary cap reached; keeping the remaining queue")
        return

    now = datetime.now(ZoneInfo("UTC"))
    # Do not let a failed video at the head of the FIFO queue block all others.
    # A cached summary is ready for Telegram delivery and does not need Gemini cooldown.
    item_index = next(
        (
            i for i, queued in enumerate(st["queue"])
            if (
                _parse_timestamp(queued.get("next_retry_at")) is None
                or _parse_timestamp(queued.get("next_retry_at")) <= now
            )
        ),
        None,
    )
    if item_index is None:
        print("[queue] all queued videos are waiting for their retry time")
        return

    item = st["queue"][item_index]
    cid = item["channel_id"]
    ch = st["channels"].get(cid)
    if ch is None:
        print(f"[queue] removing orphaned video {item.get('video_id')}: channel no longer exists")
        st["queue"].pop(item_index)
        return

    data = item.get("summary_data")
    if not data:
        last_attempt = _parse_timestamp(st.get("last_gemini_attempt_at"))
        if last_attempt and now - last_attempt < timedelta(hours=config.MIN_HOURS_BETWEEN_GEMINI_REQUESTS):
            print("[gemini] cooldown active; waiting before the next request")
            return

        # Persist the attempt time before calling Gemini so repeated manual
        # workflow dispatches cannot rapidly hammer the API after a failure.
        st["last_gemini_attempt_at"] = now.isoformat()
        try:
            data = summarizer.summarize_video(item["url"])
            # Cache before Telegram send. If Telegram fails, the next run retries
            # delivery without paying for another Gemini generation.
            item["summary_data"] = data
            item.pop("last_summary_error", None)
        except summarizer.QuotaExhausted as e:
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
            _schedule_retry(item, e)
            traceback.print_exc()
            return

    try:
        tg.send_message(
            config.TELEGRAM_CHAT_ID,
            summarizer.summary_to_telegram(item, ch["title"], data),
        )
    except Exception as e:
        # Keep the cached summary and retry delivery without calling Gemini again.
        item["last_telegram_error"] = str(e)[:1000]
        print(f"[telegram] send failed; cached summary retained for {item['video_id']}: {e}")
        return

    st["queue"].pop(item_index)
    ch["seen"].append(item["video_id"])
    item.pop("summary_data", None)
    item.pop("next_retry_at", None)
    item.pop("last_summary_error", None)
    item.pop("last_telegram_error", None)
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
