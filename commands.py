"""Process incoming Telegram commands and inline-button callbacks."""
from . import config, state as state_mod, telegram_api as tg, youtube

HELP = """*Happy Birthday Kwong* 🎂 — your global political economy digest

*Commands*
/add `<@handle or channel URL>` — follow a channel
/remove `<@handle or number from /list>` — unfollow
/list — channels being followed
/status — queue, quota and today's count
/help — this message

When you add a channel I will ask how much history to backfill. New uploads are
summarized automatically (checks run hourly) and delivered here, with an updated
mind map of the channel's ideas."""


def allowed(chat_id) -> bool:
    return str(chat_id) in config.ALLOWED_CHAT_IDS


def process_updates(st: dict) -> bool:
    """Returns True if state changed."""
    changed = False
    updates = tg.get_updates(st.get("telegram_offset", 0))
    for u in updates:
        st["telegram_offset"] = max(st.get("telegram_offset", 0), u["update_id"])
        changed = True
        if "callback_query" in u:
            _handle_callback(st, u["callback_query"])
        elif "message" in u and "text" in u["message"]:
            _handle_message(st, u["message"])
    return changed


def _handle_message(st: dict, msg: dict) -> None:
    chat_id = msg["chat"]["id"]
    if not allowed(chat_id):
        return
    text = msg["text"].strip()
    cmd, _, arg = text.partition(" ")
    cmd = cmd.split("@")[0].lower()
    arg = arg.strip()

    if cmd in ("/start", "/help"):
        tg.send_message(chat_id, HELP)

    elif cmd == "/add":
        if not arg:
            tg.send_message(chat_id, "Usage: /add @channelhandle or a channel URL")
            return
        try:
            ch = youtube.resolve_channel(arg)
        except Exception as e:
            tg.send_message(chat_id, f"YouTube lookup failed: {e}", markdown=False)
            return
        if not ch:
            tg.send_message(chat_id, f"Could not find a channel for “{arg}”.", markdown=False)
            return
        cid = ch["channel_id"]
        if cid in st["channels"]:
            tg.send_message(chat_id, f"Already following *{ch['title']}*.")
            return
        st["awaiting_backfill"][cid] = {"title": ch["title"], "thumb": ch.get("thumb", "")}
        tg.send_message(
            chat_id,
            f"Found *{ch['title']}*. How much of its past should I digest?",
            reply_markup=tg.backfill_keyboard(cid),
        )

    elif cmd == "/remove":
        target = _match_channel(st, arg)
        if not target:
            tg.send_message(chat_id, "Not found. Use /list and try /remove <number>.")
            return
        title = st["channels"][target]["title"]
        del st["channels"][target]
        st["queue"] = [q for q in st["queue"] if q["channel_id"] != target]
        tg.send_message(chat_id, f"Removed *{title}*. Its archive stays in Drive/GitHub.")

    elif cmd == "/list":
        if not st["channels"]:
            tg.send_message(chat_id, "No channels yet. Add one with /add @handle")
            return
        lines = ["*Following:*"]
        for i, (cid, ch) in enumerate(sorted(st["channels"].items(),
                                             key=lambda kv: kv[1]["title"].lower()), 1):
            lines.append(f"{i}. {ch['title']}  ({len(ch.get('seen', []))} videos digested)")
        tg.send_message(chat_id, "\n".join(lines))

    elif cmd == "/status":
        remaining = state_mod.daily_remaining(st)
        lines = [
            f"Queue: {len(st['queue'])} video(s) waiting",
            f"Digested today: {st['daily'].get('count', 0)}",
            f"Free-tier budget left today: {remaining if config.FREE_MODE else 'unlimited (paid mode)'}",
        ]
        tg.send_message(chat_id, "\n".join(lines), markdown=False)


def _match_channel(st: dict, arg: str) -> str | None:
    arg = arg.strip().lstrip("@").lower()
    if not arg:
        return None
    ordered = sorted(st["channels"].items(), key=lambda kv: kv[1]["title"].lower())
    if arg.isdigit():
        idx = int(arg) - 1
        if 0 <= idx < len(ordered):
            return ordered[idx][0]
    for cid, ch in ordered:
        if arg in ch["title"].lower() or arg == cid.lower():
            return cid
    return None


def _handle_callback(st: dict, cb: dict) -> None:
    chat_id = cb["message"]["chat"]["id"]
    if not allowed(chat_id):
        tg.answer_callback(cb["id"])
        return
    data = cb.get("data", "")
    parts = data.split("|")
    if len(parts) != 3 or parts[0] != "bf":
        tg.answer_callback(cb["id"])
        return
    _, cid, code = parts
    pending = st["awaiting_backfill"].pop(cid, None)
    tg.answer_callback(cb["id"], "Got it")
    tg.edit_reply_markup(chat_id, cb["message"]["message_id"])
    if pending is None:
        return

    days = next((d for label, c, d in config.BACKFILL_OPTIONS if c == code), 0)
    label = next((label for label, c, d in config.BACKFILL_OPTIONS if c == code), code)

    st["channels"][cid] = {
        "title": pending["title"], "thumb": pending.get("thumb", ""),
        "added_at": "", "backfill": code, "seen": [],
    }

    if code == "none":
        # Mark current uploads as seen so only future videos trigger digests
        try:
            for v in youtube.latest_from_rss(cid):
                st["channels"][cid]["seen"].append(v["video_id"])
        except Exception:
            pass
        tg.send_message(chat_id,
                        f"✅ Following *{pending['title']}*. "
                        "I'll digest every new upload from now on.")
        return

    try:
        videos = youtube.backfill_videos(cid, days)
    except Exception as e:
        tg.send_message(chat_id, f"Backfill lookup failed: {e}", markdown=False)
        videos = []

    for v in videos:
        v["channel_id"] = cid
        st["queue"].append(v)

    note = ""
    if config.FREE_MODE and len(videos) > config.DAILY_VIDEO_CAP:
        est_days = -(-len(videos) // config.DAILY_VIDEO_CAP)  # ceil
        note = (f"\n\n⏳ Free mode processes up to {config.DAILY_VIDEO_CAP} videos/day, "
                f"so the full backfill will take ≈{est_days} days. This keeps everything "
                "at $0 — no charges, ever, unless you attach billing yourself.")
    tg.send_message(chat_id,
                    f"✅ Following *{pending['title']}* — {label}: "
                    f"{len(videos)} video(s) queued for digestion.{note}")
