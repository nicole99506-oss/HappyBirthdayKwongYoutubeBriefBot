"""Thin wrapper around the Telegram Bot HTTP API (no external bot framework)."""
import requests

from . import config

BASE = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}"


def get_updates(offset: int) -> list:
    r = requests.get(
        f"{BASE}/getUpdates",
        params={"offset": offset + 1, "timeout": 0, "allowed_updates": '["message","callback_query"]'},
        timeout=30,
    )
    r.raise_for_status()
    return r.json().get("result", [])


def send_message(chat_id: str, text: str, reply_markup: dict | None = None,
                 markdown: bool = True) -> dict:
    payload = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
    if markdown:
        payload["parse_mode"] = "Markdown"
    if reply_markup:
        payload["reply_markup"] = reply_markup
    r = requests.post(f"{BASE}/sendMessage", json=payload, timeout=30)
    if not r.ok and markdown:
        # Markdown parse errors (e.g. underscores in titles) -> retry as plain text
        payload.pop("parse_mode", None)
        r = requests.post(f"{BASE}/sendMessage", json=payload, timeout=30)
    r.raise_for_status()
    return r.json()


def send_photo(chat_id: str, png_path: str, caption: str = "") -> None:
    with open(png_path, "rb") as f:
        r = requests.post(
            f"{BASE}/sendPhoto",
            data={"chat_id": chat_id, "caption": caption[:1024]},
            files={"photo": f},
            timeout=60,
        )
    r.raise_for_status()


def answer_callback(callback_id: str, text: str = "") -> None:
    requests.post(f"{BASE}/answerCallbackQuery",
                  json={"callback_query_id": callback_id, "text": text}, timeout=30)


def edit_reply_markup(chat_id: str, message_id: int) -> None:
    """Remove inline buttons after a choice is made."""
    requests.post(f"{BASE}/editMessageReplyMarkup",
                  json={"chat_id": chat_id, "message_id": message_id}, timeout=30)


def backfill_keyboard(channel_id: str) -> dict:
    rows = [[{"text": label, "callback_data": f"bf|{channel_id}|{code}"}]
            for label, code, _days in config.BACKFILL_OPTIONS]
    return {"inline_keyboard": rows}
