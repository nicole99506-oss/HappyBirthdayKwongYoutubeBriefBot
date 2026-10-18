# Project Guide — Summary-only Telegram Bot

## Current workflow

```text
GitHub Actions (hourly)
          |
          v
Read Telegram commands + YouTube RSS
          |
          v
Persistent channel list and video queue
          |
          v
At most one Gemini request for one video
          |
          v
Send concise summary to Telegram
          |
          v
Save bot state only
```

The active entry point is `python -m src.main`, launched by `.github/workflows/digest.yml`.

## Modules

- `src/main.py`: workflow orchestration, queueing, conservative quota handling, and Telegram delivery.
- `src/config.py`: environment variables, model selection, daily cap, timezone, and state path.
- `src/commands.py`: channel-management Telegram commands.
- `src/youtube.py`: RSS discovery and YouTube API channel lookup/backfill.
- `src/summarizer.py`: caption-first Gemini briefing with the original full prompt; falls back to direct video input when captions are unavailable.
- `src/telegram_api.py`: Telegram API calls.
- `src/state.py`: tracked channels, seen video IDs, queue, and daily counters.
- `.github/workflows/digest.yml`: schedule and deployment configuration.

## Cost and rate-limit safeguards

- Workflow polling: hourly; Gemini request cooldown: at least two hours, including after failed requests; no automatic in-run retries.
- Per-run cap: one video.
- No fixed daily summary cap; quota/rate-limit errors pause further attempts until the next Singapore day.
- Prompt/output: preserve the original detailed JSON briefing fields.
- No second request for mind maps, formatting, archive generation, or a reading site.
- On Gemini 429 / quota exhaustion, stop Gemini calls for the remainder of the Singapore day.
- On other errors, keep the current video queued and do not retry immediately.
- Only `data/state.json` is committed by the workflow.

The two-hour cooldown and one-video-per-run setting reduce request frequency but cannot guarantee availability or prevent every quota error. A long video can still require substantial input processing even even though output length is not capped.

## Data retained

Only `data/state.json` is actively updated. It is required to remember tracked channels, video IDs already delivered, queued items, Telegram update offset, and daily counters. Existing summary archives, mind maps, and generated site files may remain in the repository as historical files but are no longer regenerated or synced.

## Safe future cleanup

The duplicate root-level Python modules and the disabled `src/site.py`, `src/mindmap.py`, and `src/drive_sync.py` modules have been removed. Previously generated HTML and archive files may remain in the repository, but the active workflow does not rebuild them.

## Troubleshooting

1. Open GitHub Actions and inspect the first error in the run log.
2. Check that `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `GEMINI_API_KEY`, and `YOUTUBE_API_KEY` exist.
3. For quota/rate-limit errors, do not manually rerun repeatedly. The bot pauses Gemini calls until the next Singapore day.
4. For model errors, confirm `GEMINI_MODEL` is available to the API project.
5. Check `data/state.json` for the queue and daily count; do not delete it to "reset" the bot unless you intend to lose its tracking state.
