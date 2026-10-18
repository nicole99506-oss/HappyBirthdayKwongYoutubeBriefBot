# Project Guide — Summary-only Telegram Bot

## Current workflow

```text
GitHub Actions (every 3 hours)
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
- `src/summarizer.py`: one concise Gemini request per video; no automatic retries.
- `src/telegram_api.py`: Telegram API calls.
- `src/state.py`: tracked channels, seen video IDs, queue, and daily counters.
- `.github/workflows/digest.yml`: schedule and deployment configuration.

## Cost and rate-limit safeguards

- Workflow polling: hourly; Gemini request cooldown: at least six hours, including after failed requests.
- Per-run cap: one video.
- Daily cap: four successful summaries per Singapore calendar day.
- Prompt/output: one short JSON field, maximum 500 output tokens.
- No second request for mind maps, formatting, archive generation, or a reading site.
- On Gemini 429 / quota exhaustion, stop Gemini calls for the remainder of the Singapore day.
- On other errors, keep the current video queued and do not retry immediately.
- Only `data/state.json` is committed by the workflow.

The caps are conservative controls, not a promise that every video will fit a provider's free-tier input/output limits. A long video can still require substantial input processing even when the output is short.

## Data retained

Only `data/state.json` is actively updated. It is required to remember tracked channels, video IDs already delivered, queued items, Telegram update offset, and daily counters. Existing summary archives, mind maps, and generated site files may remain in the repository as historical files but are no longer regenerated or synced.

## Safe future cleanup

The repository contains legacy root-level Python files alongside the active `src/` package. The workflow imports `src.main`, so root-level copies are not used by the current scheduled entry point. Before deleting them, search for references and confirm no other workflow or manual command relies on them.

## Troubleshooting

1. Open GitHub Actions and inspect the first error in the run log.
2. Check that `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `GEMINI_API_KEY`, and `YOUTUBE_API_KEY` exist.
3. For quota/rate-limit errors, do not manually rerun repeatedly. The bot pauses Gemini calls until the next Singapore day.
4. For model errors, confirm `GEMINI_MODEL` is available to the API project.
5. Check `data/state.json` for the queue and daily count; do not delete it to "reset" the bot unless you intend to lose its tracking state.
