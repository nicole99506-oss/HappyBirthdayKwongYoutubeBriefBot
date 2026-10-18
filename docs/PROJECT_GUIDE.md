# Project Structure and Maintenance Guide

This document is a practical map of the repository for future maintenance.

## 1. Current architecture

```text
YouTube channel RSS
       |
       v
Discover new uploads -----> persistent queue/state
       |                         |
       +-------------------------+
                                 v
                         Gemini summarization
                                 |
                 +---------------+----------------+
                 v               v                v
             Telegram        Summary JSON      Knowledge tree
                                                   |
                                                   v
                                              Mind-map image

Saved summaries -----------------------> Static reading site
Saved summaries -----------------------> Optional Google Drive sync
```

This describes the intended flow visible in the code. Actual execution order is controlled by the GitHub Actions workflow and the active Python package.

## 2. Important modules

- **`main.py`** — coordinates one run: Telegram command handling, RSS polling, queue processing, summary delivery, mind-map updates, Drive sync, and site generation.
- **`config.py`** — central settings and environment-variable names. Check this before changing secrets, model names, paths, timezone, or free-tier caps.
- **`commands.py`** — Telegram command handlers, including channel management and backfill actions.
- **`youtube.py`** — reads YouTube RSS and uses the YouTube Data API for channel lookup or historical backfill.
- **`summarizer.py`** — calls Gemini and formats structured summaries for Telegram and the reading site.
- **`telegram_api.py`** — wraps Telegram API requests.
- **`state.py`** — reads/writes the bot's persistent state, including tracked channels, seen IDs, queue, and daily counters.
- **`mindmap.py`** — maintains the knowledge tree and renders a PNG.
- **`site.py`** — generates the static reading site from stored summaries.
- **`drive_sync.py`** — optional Google Drive synchronization.

The repository currently has similarly named files at the root and under `src/`. The module descriptions apply to the corresponding files, but their implementations may differ.

## 3. Highest-priority cleanup item: duplicated modules

Do **not** delete duplicates yet. Before cleanup:

1. Inspect `.github/workflows/*.yml` and record the exact command used to launch Python.
2. Check imports and package layout. The relative imports (for example, `from . import config`) indicate that modules are intended to run as part of a package.
3. Compare each root-level module with its `src/` counterpart, especially `main.py`, `config.py`, `summarizer.py`, and `state.py`.
4. Identify which version contains the latest fixes.
5. Keep one canonical implementation only after the workflow is confirmed and a test run succeeds.

Until then, this documentation intentionally records both locations rather than making a risky structural change.

## 4. Configuration and secrets

The code reads credentials from environment variables. Configure them in GitHub repository settings, not in source files.

Required by the current startup checks:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `GEMINI_API_KEY`
- `YOUTUBE_API_KEY`

Optional Google Drive configuration:

- `GDRIVE_SERVICE_ACCOUNT_JSON`
- `GDRIVE_FOLDER_ID`

Optional settings also include `GEMINI_MODEL` and `ALLOWED_CHAT_IDS`. Refer to the active `config.py` for exact defaults and the complete list.

## 5. Persistent data and quota behaviour

- State tracks channel metadata, seen video IDs, the pending queue, Telegram update offset, and daily processing counts.
- Summary JSON files contain source video metadata and generated briefing content.
- The processing loop limits work per run and defers work when the daily cap is reached.
- Gemini quota exhaustion is handled separately from ordinary errors in the orchestration code.

Before changing failure handling, verify whether a failed item is requeued, discarded, or marked as seen. That decision affects whether videos are retried or silently skipped.

## 6. Operational troubleshooting

When a scheduled run fails:

1. Open **GitHub → Actions → the failed run → logs**.
2. Find the first error, not only the final traceback.
3. Identify the stage: RSS fetch, summarization, Telegram send, mind-map rendering, Drive sync, or site generation.
4. Confirm the active entry point and config file.
5. Make one change at a time and run the workflow again.
6. Verify the Telegram message and generated artifacts, not just a green workflow status.

## 7. Suggested future repository organization

After confirming the active entry point, a clean target structure could look like this:

```text
.
├── README.md
├── requirements.txt
├── .gitignore
├── .github/
│   └── workflows/
├── src/
│   └── <canonical Python package modules>
├── data/
│   ├── summaries/
│   └── state/
├── site/                 # generated output, if applicable
└── docs/
    ├── PROJECT_GUIDE.md
    └── OPERATIONS.md
```

This is a **future target**, not a description of the exact current tree. Do not move files or create empty data folders solely to match this sketch; first confirm paths used by the running workflow.

## 8. What this documentation does not claim

- It does not confirm that all integrations work end to end.
- It does not verify current provider quota or billing status.
- It does not prove which duplicate module set is used in production.
- It does not recommend deleting any existing file before the workflow and import paths are checked.
