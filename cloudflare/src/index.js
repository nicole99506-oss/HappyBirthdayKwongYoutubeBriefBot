export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/health") {
      return json({ ok: true, service: "telegram-webhook" });
    }

    if (url.pathname.startsWith("/internal/")) {
      if (!env.BOT_INTERNAL_TOKEN ||
          request.headers.get("Authorization") !== `Bearer ${env.BOT_INTERNAL_TOKEN}`) {
        return json({ error: "unauthorized" }, 401);
      }
      if (request.method === "POST" && url.pathname === "/internal/bootstrap") {
        const body = await request.json();
        const marker = await env.DB.prepare("SELECT value FROM settings WHERE key = 'channels_bootstrapped'").first();
        if (!marker) {
          const channels = Array.isArray(body.channels) ? body.channels : [];
          for (const ch of channels) {
            await env.DB.prepare(
              "INSERT OR IGNORE INTO channels (channel_id, title, thumb, backfill, initialized) VALUES (?, ?, ?, ?, 1)"
            ).bind(String(ch.channel_id), String(ch.title || ch.channel_id), String(ch.thumb || ""),
              String(ch.backfill || "none")).run();
          }
          await env.DB.prepare("INSERT INTO settings (key, value) VALUES ('channels_bootstrapped', '1')").run();
          return json({ ok: true, imported: channels.length, already_bootstrapped: false });
        }
        return json({ ok: true, imported: 0, already_bootstrapped: true });
      }
      if (request.method === "GET" && url.pathname === "/internal/channels") {
        const result = await env.DB.prepare(
          "SELECT channel_id, title, thumb, backfill, initialized, added_at FROM channels ORDER BY title COLLATE NOCASE"
        ).all();
        return json({ channels: result.results || [] });
      }
      if (request.method === "POST" && url.pathname === "/internal/channels/initialized") {
        const body = await request.json();
        await env.DB.prepare("UPDATE channels SET initialized = 1 WHERE channel_id = ?")
          .bind(String(body.channel_id || "")).run();
        return json({ ok: true });
      }
      if (request.method === "POST" && url.pathname === "/internal/status") {
        const body = await request.json();
        await env.DB.prepare(
          "INSERT INTO bot_status (id, payload, updated_at) VALUES (1, ?, CURRENT_TIMESTAMP) " +
          "ON CONFLICT(id) DO UPDATE SET payload=excluded.payload, updated_at=CURRENT_TIMESTAMP"
        ).bind(JSON.stringify(body)).run();
        return json({ ok: true });
      }
      if (request.method === "GET" && url.pathname === "/internal/status") {
        const row = await env.DB.prepare("SELECT payload FROM bot_status WHERE id = 1").first();
        return json(row ? JSON.parse(row.payload) : { message: "Digest status has not been reported yet." });
      }
      return json({ error: "not found" }, 404);
    }

    if (url.pathname !== "/telegram" || request.method !== "POST") {
      return json({ error: "not found" }, 404);
    }
    // The webhook secret is mandatory. Never accept public webhook requests if it is unset.
    if (!env.TELEGRAM_WEBHOOK_SECRET ||
        request.headers.get("X-Telegram-Bot-Api-Secret-Token") !== env.TELEGRAM_WEBHOOK_SECRET) {
      return json({ error: "unauthorized" }, 401);
    }

    let update;
    try { update = await request.json(); }
    catch { return json({ error: "bad json" }, 400); }

    // Acknowledge Telegram immediately; process API/D1 work in the background.
    ctx.waitUntil((async () => {
      try {
        if (update.callback_query) await handleCallback(update.callback_query, env);
        else if (update.message?.text) await handleMessage(update.message, env);
      } catch (err) {
        console.error("update handler failed", err?.stack || err);
      }
    })());
    return json({ ok: true });
  }
};

async function handleMessage(msg, env) {
  const chatId = String(msg.chat?.id ?? "");
  if (!chatAllowed(chatId, env)) return;
  const text = (msg.text || "").trim();
  const firstSpace = text.indexOf(" ");
  let command = (firstSpace < 0 ? text : text.slice(0, firstSpace)).toLowerCase();
  command = command.replace(/^\//, "").split("@")[0];
  const arg = firstSpace < 0 ? "" : text.slice(firstSpace + 1).trim();

  if (command === "add") {
    if (!arg) {
      await sendMessage(env, chatId, "請輸入：add YouTube 頻道名稱或連結");
      return;
    }
    let channel;
    try {
      channel = await resolveChannel(arg, env);
    } catch (err) {
      console.error("YouTube channel lookup failed", err?.stack || err);
      await sendMessage(env, chatId, "YouTube 頻道查詢失敗，請稍後再試；沒有新增任何頻道。");
      return;
    }
    if (!channel) {
      await sendMessage(env, chatId, `找不到 YouTube 頻道：${arg}`);
      return;
    }
    const exists = await env.DB.prepare("SELECT title FROM channels WHERE channel_id = ?")
      .bind(channel.channel_id).first();
    if (exists) {
      await sendMessage(env, chatId, `已經在追蹤「${exists.title}」了。`);
      return;
    }
    await env.DB.prepare(
      "INSERT INTO pending_adds (chat_id, channel_id, title, thumb, created_at) " +
      "VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP) " +
      "ON CONFLICT(chat_id) DO UPDATE SET channel_id=excluded.channel_id, title=excluded.title, " +
      "thumb=excluded.thumb, created_at=CURRENT_TIMESTAMP"
    ).bind(chatId, channel.channel_id, channel.title, channel.thumb || "").run();
    await sendMessage(env, chatId,
      `Please confirm add "${channel.title}" as a new channel?\n\n回覆 confirm 確認新增，或回覆 cancel 取消。`);
    return;
  }

  if (command === "confirm") {
    const pending = await env.DB.prepare(
      "SELECT channel_id, title, thumb FROM pending_adds WHERE chat_id = ?"
    ).bind(chatId).first();
    if (!pending) {
      await sendMessage(env, chatId, "沒有待確認的新增頻道。請先傳送 add 加上頻道名稱或連結。");
      return;
    }
    await env.DB.prepare(
      "INSERT INTO channels (channel_id, title, thumb, backfill, initialized) VALUES (?, ?, ?, 'none', 0) " +
      "ON CONFLICT(channel_id) DO NOTHING"
    ).bind(pending.channel_id, pending.title, pending.thumb || "").run();
    await env.DB.prepare("DELETE FROM pending_adds WHERE chat_id = ?").bind(chatId).run();
    await sendMessage(env, chatId,
      `✅ 已新增「${pending.title}」。從現在起只會推送加入後發布的新影片，不會補送歷史影片。`);
    return;
  }

  if (command === "cancel") {
    await env.DB.prepare("DELETE FROM pending_adds WHERE chat_id = ?").bind(chatId).run();
    await sendMessage(env, chatId, "已取消新增頻道。");
    return;
  }

  if (command === "list") {
    const result = await env.DB.prepare(
      "SELECT channel_id, title FROM channels ORDER BY title COLLATE NOCASE"
    ).all();
    const channels = result.results || [];
    if (!channels.length) {
      await sendMessage(env, chatId, "目前沒有追蹤中的頻道。傳送 add 加上頻道名稱或連結即可新增。");
      return;
    }
    await sendMessage(env, chatId, "目前追蹤的頻道（點擊按鈕即可移除）：", {
      inline_keyboard: channels.map(ch => [{
        text: `移除：${ch.title}`, callback_data: `rm|${ch.channel_id}`
      }])
    });
    return;
  }

  if (command === "status") {
    const status = await env.DB.prepare("SELECT payload FROM bot_status WHERE id = 1").first();
    await sendMessage(env, chatId, status?.payload
      ? formatStatus(JSON.parse(status.payload))
      : "摘要服務尚未回報狀態；GitHub Actions 下次執行後會更新。");
    return;
  }

  // Ignore unrelated ordinary chat; do not expose a help command.
}

async function handleCallback(cb, env) {
  const chatId = String(cb.message?.chat?.id ?? "");
  if (!chatAllowed(chatId, env)) {
    await answerCallback(env, cb.id, "Not authorized");
    return;
  }
  const parts = String(cb.data || "").split("|");
  if (parts[0] === "rm" && parts[1]) {
    const row = await env.DB.prepare("SELECT title FROM channels WHERE channel_id = ?")
      .bind(parts[1]).first();
    await env.DB.prepare("DELETE FROM channels WHERE channel_id = ?").bind(parts[1]).run();
    await answerCallback(env, cb.id, row ? "已移除" : "頻道已不存在");
    if (row) await sendMessage(env, chatId, `已移除「${row.title}」。下次 GitHub 摘要執行時會同步更新。`);
    return;
  }
  await answerCallback(env, cb.id);
}

async function resolveChannel(query, env) {
  const mId = query.match(/(UC[0-9A-Za-z_-]{22})/);
  let data;
  if (mId) {
    data = await ytGet("channels", { part: "snippet", id: mId[1] }, env);
  } else {
    const mHandle = query.match(/youtube\.com\/@([\w.\-]+)/i) || query.match(/^@?([\w.\-]+)$/);
    if (mHandle) data = await ytGet("channels", { part: "snippet", forHandle: mHandle[1] }, env);
    if (!data?.items?.length) {
      data = await ytGet("search", { part: "snippet", q: query, type: "channel", maxResults: "1" }, env);
      const id = data?.items?.[0]?.snippet?.channelId;
      if (id) data = await ytGet("channels", { part: "snippet", id }, env);
    }
  }
  const item = data?.items?.[0];
  if (!item) return null;
  const sn = item.snippet || {};
  const thumbs = sn.thumbnails || {};
  return {
    channel_id: item.id,
    title: sn.title || query,
    thumb: (thumbs.medium || thumbs.default || {}).url || ""
  };
}

async function ytGet(path, params, env) {
  const u = new URL(`https://www.googleapis.com/youtube/v3/${path}`);
  for (const [k, v] of Object.entries({ ...params, key: env.YOUTUBE_API_KEY })) u.searchParams.set(k, v);
  const response = await fetch(u);
  if (!response.ok) throw new Error(`YouTube API ${response.status}`);
  return response.json();
}

function chatAllowed(chatId, env) {
  return String(chatId) === String(env.TELEGRAM_CHAT_ID) ||
    (env.ALLOWED_CHAT_IDS || "").split(",").map(s => s.trim()).includes(String(chatId));
}

function formatStatus(s) {
  return [
    `摘要佇列：${s.queue ?? "未知"} 部影片`,
    `今日已發送：${s.daily_count ?? "未知"} 篇`,
    `上次執行：${s.last_run ?? "尚無紀錄"}`,
    `Gemini 狀態：${s.gemini_paused ? "今日因配額限制暫停" : "未回報暫停"}`
  ].join("\n");
}

async function sendMessage(env, chatId, text, replyMarkup) {
  const body = { chat_id: chatId, text, disable_web_page_preview: true };
  if (replyMarkup) body.reply_markup = replyMarkup;
  const response = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body)
  });
  if (!response.ok) throw new Error(`Telegram sendMessage failed: ${response.status}`);
}

async function answerCallback(env, callbackId, text = "") {
  await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/answerCallbackQuery`, {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ callback_query_id: callbackId, text })
  });
}

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status, headers: { "content-type": "application/json; charset=utf-8" }
  });
}
