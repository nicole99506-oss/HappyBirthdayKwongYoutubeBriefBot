# Project Guide — Summary-only Telegram Bot

## Current architecture

When Cloudflare Worker mode is configured, Telegram commands are received by a webhook and processed immediately. GitHub Actions runs hourly for YouTube RSS checks and Gemini summary generation.

```text
Telegram messages
       |
       v
Cloudflare Worker webhook ----> Cloudflare D1
       |                         - tracked channels
       |                         - pending add confirmations
       |                         - latest digest status
       v
Immediate command replies

GitHub Actions (hourly)
       |
       +--> sync tracked channels from Worker/D1
       +--> check YouTube RSS and queue new videos
       +--> summarize at most one video with Gemini
       +--> send the detailed briefing to Telegram
       +--> save queue/seen/cooldown state in data/state.json
       +--> publish status to Worker/D1
```

Until both `BOT_WORKER_URL` and `BOT_INTERNAL_TOKEN` are configured as GitHub Actions secrets, the workflow keeps the legacy Telegram polling path. Deploy the Worker and configure the GitHub secrets before setting Telegram's webhook; do not enable polling and webhook at the same time.

## Telegram command interface

- `add <YouTube channel name or URL>`: resolve the channel and ask for confirmation.
- `confirm`: confirm the pending add, then choose the history backfill range.
- `cancel`: cancel a pending add.
- `list`: show tracked channels with a remove button for each.
- `status`: show queue size, today's summaries, last run, and whether Gemini is paused.
- A leading slash is accepted too. There is no `help` command.

## Modules

- `cloudflare/src/index.js`: webhook, command handling, channel buttons, and internal API.
- `cloudflare/schema.sql`: D1 tables.
- `cloudflare/wrangler.toml`: Worker and D1 binding template.
- `cloudflare/SETUP.md`: deployment and safe migration steps.
- `src/main.py`: digest orchestration, queueing, quota handling, and Telegram delivery.
- `src/worker_sync.py`: one-time migration of existing tracked channels and ongoing Worker/D1 sync.
- `src/config.py`: environment variables, model, request cooldown, timezone, and state path.
- `src/commands.py`: legacy polling command handler, used only until Worker mode is configured.
- `src/youtube.py`: RSS discovery and YouTube API channel lookup/backfill.
- `src/summarizer.py`: caption-first Gemini briefing with the original detailed prompt.
- `src/telegram_api.py`: Telegram API calls.
- `src/state.py`: local digest queue, seen video IDs, and daily counters.
- `.github/workflows/digest.yml`: hourly summary workflow.

## Cost and rate-limit safeguards

- One video maximum per workflow run.
- Minimum one-hour cooldown between Gemini requests, including after failed requests.
- No fixed daily summary cap; quota/rate-limit errors pause further attempts until the next Singapore day.
- No automatic in-run retries.
- The original detailed summary prompt remains unchanged.
- No mind maps, archives, Drive sync, or reading site generation.

## Data ownership

Cloudflare D1 owns channel membership, pending add confirmation, and the latest status displayed by `status`. The first Worker-mode digest run imports existing tracked channels from `data/state.json` once, then D1 becomes the source of truth for membership. The repository's `data/state.json` continues to store the digest queue, delivered video IDs, daily counters, and Gemini cooldown. Removing a channel in Telegram is immediate in D1; the next hourly digest run synchronizes that removal and drops queued items for that channel.

## Troubleshooting

1. Open GitHub Actions and inspect the first error in the run log.
2. Check GitHub secrets `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `GEMINI_API_KEY`, `YOUTUBE_API_KEY`, `BOT_WORKER_URL`, and `BOT_INTERNAL_TOKEN`.
3. Check Cloudflare Worker logs for webhook or D1 errors.
4. For Gemini quota/rate-limit errors, do not manually rerun repeatedly; the bot pauses Gemini calls until the next Singapore day.
5. Do not delete `data/state.json` to reset the bot unless you intend to lose its queue and seen-video tracking.
