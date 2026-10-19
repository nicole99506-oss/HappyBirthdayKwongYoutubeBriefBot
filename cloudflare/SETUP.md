# Cloudflare Telegram Webhook setup

This migration is staged to be safe: **do not set Telegram's webhook until the Worker is deployed and the GitHub Actions secrets are configured**. Until both GitHub secrets are present, the digest workflow keeps using the old `getUpdates` polling path.

## What this changes

- Telegram commands are handled immediately by a Cloudflare Worker.
- Cloudflare D1 is the source of truth for channel membership, pending add confirmations, and the status shown by `status`.
- GitHub Actions continues to run hourly for YouTube RSS checks and Gemini summaries.
- The Python digest synchronizes channel membership from D1 at the start of each run. Queue, seen video IDs, and Gemini cooldown state remain in `data/state.json`.
- The Worker only accepts commands from `TELEGRAM_CHAT_ID` or IDs in `ALLOWED_CHAT_IDS`.

## 1. Create the D1 database

Install Node.js if it is not already installed. Open a terminal in the repository and run:

```powershell
cd cloudflare
npx wrangler login
npx wrangler d1 create youtube-telegram-bot
```

Copy the `database_id` returned by Wrangler. Open `cloudflare/wrangler.toml` and replace `REPLACE_WITH_YOUR_D1_DATABASE_ID` with that ID.

Create the tables:

```powershell
npx wrangler d1 execute youtube-telegram-bot --remote --file=cloudflare/schema.sql --config cloudflare/wrangler.toml
```

Run that command from the repository root. If you are already in the `cloudflare` directory, use `--file=schema.sql`.

## 2. Configure Worker secrets

From the repository root, run each command and paste the requested value when Wrangler prompts for it:

```powershell
npx wrangler secret put TELEGRAM_BOT_TOKEN --config cloudflare/wrangler.toml
npx wrangler secret put TELEGRAM_CHAT_ID --config cloudflare/wrangler.toml
npx wrangler secret put YOUTUBE_API_KEY --config cloudflare/wrangler.toml
npx wrangler secret put TELEGRAM_WEBHOOK_SECRET --config cloudflare/wrangler.toml
npx wrangler secret put BOT_INTERNAL_TOKEN --config cloudflare/wrangler.toml
```

- `TELEGRAM_BOT_TOKEN`: the existing Telegram bot token.
- `TELEGRAM_CHAT_ID`: your allowed private chat ID.
- `YOUTUBE_API_KEY`: the existing YouTube Data API key.
- `TELEGRAM_WEBHOOK_SECRET`: create a new random string using only letters, numbers, underscores, and hyphens. Do not reuse the bot token.
- `BOT_INTERNAL_TOKEN`: create a separate long random string. This protects the private API used by GitHub Actions.

Do not commit any of these values into GitHub files.

## 3. Deploy the Worker

From the repository root:

```powershell
npx wrangler deploy --config cloudflare/wrangler.toml
```

Wrangler will print a URL similar to `https://youtube-telegram-command-bot.<your-subdomain>.workers.dev`. Save it as `WORKER_URL`. Confirm `https://YOUR-WORKER-URL/health` returns JSON with `"ok":true`.

## 4. Add two GitHub Actions secrets

Open **GitHub repository → Settings → Secrets and variables → Actions → New repository secret** and add:

- `BOT_WORKER_URL`: the Worker URL only, e.g. `https://youtube-telegram-command-bot.example.workers.dev` (no trailing slash).
- `BOT_INTERNAL_TOKEN`: exactly the same value you entered for the Worker secret in step 2.

Do not add `/telegram` to `BOT_WORKER_URL`; the Python code uses the `/internal/...` endpoints.

## 5. Set Telegram's webhook

Only do this after steps 1–4 are complete. In PowerShell, fill in your existing bot token, Worker URL, and the same webhook secret you entered in step 2:

```powershell
$BotToken = "PASTE_YOUR_TELEGRAM_BOT_TOKEN"
$WorkerUrl = "https://YOUR-WORKER-URL"
$WebhookSecret = "PASTE_THE_TELEGRAM_WEBHOOK_SECRET"
$Body = @{
  url = "$WorkerUrl/telegram"
  secret_token = $WebhookSecret
  allowed_updates = @("message", "callback_query")
} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "https://api.telegram.org/bot$BotToken/setWebhook" -ContentType "application/json" -Body $Body
```

The response should include `"ok": true`. Never paste your real token or secret into a public issue or commit it to the repository.

## 6. Verify the commands

Send these messages to your bot:

1. `add <YouTube channel name or URL>`
2. Confirm that the bot resolves the channel and asks: `Please confirm add "..."` 
3. Reply `confirm`; the channel is added immediately. Only videos published after that confirmation time will be sent; older videos are not backfilled.
4. Send `list`; each tracked channel should have a remove button.
5. Send `status`; after the next successful GitHub run, it should show queue and digest status.
6. Try `cancel` after starting another add request to cancel it.

The supported command words are `add`, `confirm`, `cancel`, `list`, and `status`. A leading slash is also accepted. There is intentionally no `help` command.

## Rollback

To return to polling mode, first remove the Telegram webhook using the Bot API `deleteWebhook`, then remove the GitHub Actions secrets `BOT_WORKER_URL` and `BOT_INTERNAL_TOKEN`. The workflow will then use the existing polling path again. Do not switch these in the middle of a digest run.
