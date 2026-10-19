# Happy Birthday Kwong — YouTube Summary Bot

A small Telegram bot that follows YouTube channels, summarizes new videos with Gemini, and sends the summaries to Telegram.

The current workflow processes at most one video per run, checks YouTube hourly, and enforces a one-hour minimum between Gemini attempts. There is no fixed daily summary cap. Telegram commands can be moved to a Cloudflare Worker webhook so GitHub Actions no longer polls Telegram. Gemini quota and rate limits vary by account and model, so these safeguards reduce risk but cannot guarantee that a provider will never return a limit error.

## What it does

1. Reads new-upload RSS feeds for tracked YouTube channels.
2. Keeps a queue so videos can be processed gradually.
3. Makes one Gemini generation request per video.
4. Sends one faithful, original-language summary to Telegram, targeting about 800 words while prioritizing coverage over a strict length limit.
5. Persists only the bot state needed to remember channels, seen video IDs, the queue, and daily counters. Per-video summaries are not archived by the current workflow.

It no longer generates mind maps, saves per-video summary archives, syncs Google Drive, or rebuilds a reading website.

## Repository layout

- `.github/workflows/digest.yml` — scheduled GitHub Actions workflow.
- `src/main.py` — orchestration and queue processing.
- `src/config.py` — secrets, model, daily cap, timezone, and data paths.
- `src/commands.py` — Telegram commands and channel management.
- `src/summarizer.py` — original-language full-summary prompt, caption-first input, one-field JSON parsing, and Telegram formatting.
- `src/telegram_api.py` — Telegram Bot API helper.
- `src/youtube.py` — RSS polling and YouTube channel/backfill lookup.
- `src/state.py` — persistent state only.
- `requirements.txt` — minimal Python dependencies.
- `data/state.json` — persistent bot state committed by the workflow.

The active runtime code lives under `src/`. Duplicate root-level Python modules and the disabled mind-map, Drive-sync, and reading-site modules have been removed. Previously generated website/archive files may remain as historical artifacts, but the bot no longer rebuilds or syncs them.

## Cloudflare Worker command mode

Files for the optional webhook implementation are under `cloudflare/`. The Worker uses D1 for channel membership and status; GitHub Actions remains responsible for video summaries. Before enabling webhook mode, create a Cloudflare D1 database and apply `cloudflare/schema.sql`, set the D1 database ID in `cloudflare/wrangler.toml`, configure Worker secrets (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `YOUTUBE_API_KEY`, `TELEGRAM_WEBHOOK_SECRET`, `BOT_INTERNAL_TOKEN`), and deploy the Worker. Then add GitHub Actions repository secrets `BOT_WORKER_URL` and `BOT_INTERNAL_TOKEN`, and only then set Telegram's webhook to `https://YOUR-WORKER/telegram` with the same webhook secret. If those two GitHub secrets are empty, the existing polling path remains active, so do not set Telegram's webhook until the Worker is deployed and the GitHub secrets are ready. See `cloudflare/SETUP.md` for the step-by-step migration.

## Setup

In **Repository → Settings → Secrets and variables → Actions**, configure:

| Secret | Purpose |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token |
| `TELEGRAM_CHAT_ID` | Chat that receives summaries |
| `GEMINI_API_KEY` | Gemini API key |
| `YOUTUBE_API_KEY` | YouTube Data API key for channel lookup and historical backfill |

Optional repository variable: `GEMINI_MODEL`. The default is `gemini-2.5-flash-lite`; if this model is not enabled for your API project, set this variable to a currently available model supported by your account. Captions are fetched first where available; if unavailable, the bot falls back to Gemini's direct video input.

Never commit API keys, Telegram tokens, service-account JSON, or a populated `.env` file.

## Usage limits and failure handling

- Scheduled workflow checks YouTube RSS hourly. Once Cloudflare Worker webhook mode is configured with `BOT_WORKER_URL` and `BOT_INTERNAL_TOKEN`, Telegram commands are handled by the Worker instead of GitHub polling.
- Each run processes at most one video. Gemini requests are separated by a one-hour cooldown, including after failed requests. There are no automatic in-run retries.
- No fixed daily summary cap is configured. Processing stops or pauses when Gemini returns a quota/rate-limit error.
- The original detailed briefing prompt is preserved, including TL;DR, multi-paragraph summary, highlights, key concepts, and why-it-matters.
- A quota/rate-limit response pauses further Gemini calls until the next Singapore day.
- Other generation errors are not retried in a tight loop; the queued video remains for a later run.
- A failed Telegram delivery leaves the video queued instead of marking it as successfully delivered.

These controls reduce requests and retry storms. They cannot override Google's account-specific quotas, guarantee availability, or fully prevent a single long video from exceeding an input-token limit.

## Telegram commands

- `add <YouTube channel name or URL>` — request to add a channel; the bot asks for `confirm`. After confirmation, it starts tracking from that moment and does not backfill older videos.
- `confirm` — confirm the pending channel addition.
- `cancel` — cancel a pending addition.
- `list` — list tracked channels and show a remove button for each.
- `status` — inspect queue and daily summary count.
- Commands may also be sent with a leading slash, e.g. `/add`.

New channels do not backfill historical videos. The first RSS sync only queues videos published after the channel's confirmation/add time.

## Troubleshooting

1. Open **GitHub → Actions → Digest run** and inspect the latest run logs.
2. Confirm the required secrets are configured correctly.
3. For Gemini 429 / `RESOURCE_EXHAUSTED`, wait for the quota window to reset and check the active quota in Google AI Studio.
4. For model-not-found errors, verify `GEMINI_MODEL` is available to the API project.
5. If a workflow run fails, inspect the first error in the logs; do not repeatedly click rerun after a quota error.

## Maintenance principles

1. Keep the one-hour request cooldown and stop on Gemini quota errors.
2. Do not add a second Gemini call for formatting or knowledge maps.
3. Preserve the original detailed summary prompt and avoid processing the same video twice.
4. Keep runtime changes under `src/`; the duplicate root-level Python modules have already been removed.
