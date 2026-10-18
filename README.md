# Happy Birthday Kwong — YouTube Summary Bot

A small Telegram bot that follows YouTube channels, summarizes new videos with Gemini, and sends the summaries to Telegram.

The current workflow is intentionally conservative: **one video per run, hourly command checks, and at least two hours between Gemini attempts; there is no fixed daily summary cap**. Gemini quota and rate limits vary by account and model, so these safeguards reduce risk but cannot guarantee that a provider will never return a limit error.

## What it does

1. Reads new-upload RSS feeds for tracked YouTube channels.
2. Keeps a queue so videos can be processed gradually.
3. Makes one Gemini generation request per video.
4. Sends a concise summary to Telegram.
5. Persists only the bot state needed to remember channels, seen video IDs, the queue, and daily counters.

It no longer generates mind maps, saves per-video summary archives, syncs Google Drive, or rebuilds a reading website.

## Repository layout

- `.github/workflows/digest.yml` — scheduled GitHub Actions workflow.
- `src/main.py` — orchestration and queue processing.
- `src/config.py` — secrets, model, daily cap, timezone, and data paths.
- `src/commands.py` — Telegram commands and channel management.
- `src/summarizer.py` — original full briefing prompt, caption-first input, and Telegram formatting.
- `src/telegram_api.py` — Telegram Bot API helper.
- `src/youtube.py` — RSS polling and YouTube channel/backfill lookup.
- `src/state.py` — persistent state only.
- `requirements.txt` — minimal Python dependencies.
- `data/state.json` — persistent bot state committed by the workflow.

The active runtime code lives under `src/`. Duplicate root-level Python modules and the disabled mind-map, Drive-sync, and reading-site modules have been removed. Previously generated website/archive files may remain as historical artifacts, but the bot no longer rebuilds or syncs them.

## Setup

In **Repository → Settings → Secrets and variables → Actions**, configure:

| Secret | Purpose |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token |
| `TELEGRAM_CHAT_ID` | Chat that receives summaries |
| `GEMINI_API_KEY` | Gemini API key |
| `YOUTUBE_API_KEY` | YouTube Data API key for channel lookup and historical backfill |

Optional repository variable: `GEMINI_MODEL`. The default is `gemini-2.5-flash-lite`; if this model is not enabled for your API project, set this variable to a currently available model supported by your account.

Never commit API keys, Telegram tokens, service-account JSON, or a populated `.env` file.

## Usage limits and failure handling

- Scheduled workflow checks Telegram commands and YouTube RSS hourly.
- Each run processes at most one video. Gemini requests are separated by a two-hour cooldown, including after failed non-quota requests.
- No fixed daily summary cap is configured. Processing stops or pauses when Gemini returns a quota/rate-limit error.
- The original detailed briefing prompt is preserved, including TL;DR, multi-paragraph summary, highlights, key concepts, and why-it-matters.
- A quota/rate-limit response pauses further Gemini calls until the next Singapore day.
- Other generation errors are not retried in a tight loop; the queued video remains for a later run.
- A failed Telegram delivery leaves the video queued instead of marking it as successfully delivered.

These controls reduce requests and retry storms. They cannot override Google's account-specific quotas, guarantee availability, or fully prevent a single long video from exceeding an input-token limit.

## Telegram commands

- `/add @handle` — follow a channel and choose how much history to backfill.
- `/remove <number or channel>` — stop following a channel.
- `/list` — list followed channels.
- `/status` — inspect queue and daily summary count.
- `/help` — show help.

Historical backfills may enqueue many videos; they are processed gradually with a two-hour minimum between Gemini attempts.

## Troubleshooting

1. Open **GitHub → Actions → Digest run** and inspect the latest run logs.
2. Confirm the required secrets are configured correctly.
3. For Gemini 429 / `RESOURCE_EXHAUSTED`, wait for the quota window to reset and check the active quota in Google AI Studio.
4. For model-not-found errors, verify `GEMINI_MODEL` is available to the API project.
5. If a workflow run fails, inspect the first error in the logs; do not repeatedly click rerun after a quota error.

## Maintenance principles

1. Keep the two-hour request cooldown until several days of successful runs are observed.
2. Do not add a second Gemini call for formatting or knowledge maps.
3. Preserve the original detailed summary prompt and avoid processing the same video twice.
4. Keep runtime changes under `src/`; the duplicate root-level Python modules have already been removed.
