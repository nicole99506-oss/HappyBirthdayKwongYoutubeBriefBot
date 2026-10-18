# Happy Birthday Kwong — YouTube Brief Bot

A Telegram bot that follows YouTube channels, creates AI-generated video briefings, and maintains a searchable reading site and knowledge maps.

> This README documents the current repository based on the code inspected. It does not imply that every optional integration has been tested end to end.

## What it does

1. **Discover videos** — checks channel RSS feeds for new uploads.
2. **Manage channels** — handles Telegram commands for adding/removing channels and requesting historical backfills.
3. **Summarize videos** — uses the Google Gemini API to create structured briefings.
4. **Deliver briefings** — sends summaries to Telegram and can send updated knowledge-map images.
5. **Keep history** — stores summary JSON files and persistent bot state in the repository.
6. **Publish a reading site** — rebuilds a static site from saved summaries.
7. **Optional Google Drive sync** — syncs channel summaries when Drive configuration is enabled.
8. **Respect usage limits** — configuration includes per-run and per-day processing caps intended to limit free-tier usage.

## Repository layout

The repository currently contains both root-level Python modules and a `src/` directory with similarly named modules. Treat this as a cleanup item: **do not delete or move either copy until the GitHub Actions entry point and import paths have been verified.**

| Path | Purpose |
| --- | --- |
| `src/main.py` / `main.py` | Main orchestration: discover uploads, process the queue, send results, and rebuild the site. |
| `src/config.py` / `config.py` | Environment variables, model selection, paths, and usage limits. |
| `src/commands.py` / `commands.py` | Telegram bot commands and callbacks. |
| `src/summarizer.py` / `summarizer.py` | Gemini video summarization and formatting. |
| `src/telegram_api.py` / `telegram_api.py` | Telegram API helpers. |
| `src/youtube.py` / `youtube.py` | YouTube RSS, channel lookup, and historical video discovery. |
| `src/state.py` / `state.py` | Persistent state, channel tracking, queue, and daily counters. |
| `src/mindmap.py` / `mindmap.py` | Knowledge-tree storage and image rendering. |
| `src/site.py` / `site.py` | Static reading-site generation. |
| `src/drive_sync.py` / `drive_sync.py` | Optional Google Drive synchronization. |
| `requirements.txt` | Python dependencies. |
| `.github/workflows/` | GitHub Actions automation; inspect the actual workflow before changing the run command or schedule. |

Some paths may differ or be absent in a particular revision. Use the actual files on the default branch as the source of truth.

## Setup

### 1. Python dependencies

Install the dependencies listed in `requirements.txt`:

```bash
python -m pip install -r requirements.txt
```

### 2. GitHub Actions secrets

Open **Repository → Settings → Secrets and variables → Actions**. Configure the secrets used by the workflow:

| Secret | Required? | Purpose |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | Yes | Telegram bot authentication token. |
| `TELEGRAM_CHAT_ID` | Yes | Destination chat for briefings and bot notifications. |
| `GEMINI_API_KEY` | Yes | Gemini API access for summaries. |
| `YOUTUBE_API_KEY` | Required by current startup checks | YouTube Data API access for channel resolution/backfill. |
| `GDRIVE_SERVICE_ACCOUNT_JSON` | Optional | Service-account JSON for Drive sync. |
| `GDRIVE_FOLDER_ID` | Optional | Destination Drive folder. |

Optional repository variables/environment settings referenced by the code include `GEMINI_MODEL` and `ALLOWED_CHAT_IDS`. Check `config.py` for the current defaults and other settings.

**Security:** never commit API keys, bot tokens, service-account credentials, or a populated `.env` file. Rotate any credential that has accidentally been exposed.

## Runtime and usage limits

The code includes a per-run processing limit, a daily video cap, and logic to defer queued videos when the cap is reached or Gemini reports quota exhaustion. Exact values and timezone are defined in `config.py`; review that file before changing the schedule or limits.

A configured free-tier guard is a precaution, not a guarantee about a provider's account or billing configuration. Confirm provider limits and billing settings separately.

## Where data is stored

The code writes summary JSON files under the configured summary directory and maintains a state file for tracked channels, seen video IDs, pending items, and daily counters. The generated reading site and knowledge maps are built from this stored data. Exact paths are defined in `config.py`.

Because the workflow may commit updated state/data back to the repository, check the Actions workflow and `.gitignore` before changing persistence behaviour. Avoid committing credentials or other private data.

## Troubleshooting checklist

1. Open **Actions** and inspect the latest workflow run and its logs.
2. Confirm all required secrets exist and are named exactly as the code expects.
3. For Telegram failures, verify the bot token, destination chat ID, and that the bot can message that chat.
4. For Gemini errors, distinguish quota/rate-limit errors (often HTTP 429) from temporary service/model errors (often HTTP 5xx such as 503).
5. Check whether the video remains in the queue or has been marked as seen after a failure.
6. Confirm the workflow is running the intended module under `src/` or the repository root; duplicate modules currently make this especially important.

## Safe maintenance order

1. Confirm which workflow and Python entry point are actually used.
2. Compare the root-level modules with `src/` and identify the active copy.
3. Add or update tests before changing runtime logic.
4. Only then remove duplicated files or reorganize the package.
5. Test a workflow run and verify real Telegram delivery after each functional change.

## Project documents

- [Project structure and maintenance notes](docs/PROJECT_GUIDE.md)
