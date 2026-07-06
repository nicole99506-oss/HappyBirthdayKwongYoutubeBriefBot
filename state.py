"""Persistent state, committed back to the repo by the workflow after each run."""
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from . import config


def _today() -> str:
    return datetime.now(ZoneInfo(config.TIMEZONE)).strftime("%Y-%m-%d")


DEFAULT_STATE = {
    "telegram_offset": 0,
    # channel_id -> {title, handle, added_at, backfill, seen: [video_ids], thumb}
    "channels": {},
    # channel_id awaiting a backfill button press -> {title, handle}
    "awaiting_backfill": {},
    # FIFO queue of videos to summarize: {channel_id, video_id, title, published, url, backfill}
    "queue": [],
    # daily counter for the free-mode cap
    "daily": {"date": "", "count": 0},
    # set true once we've greeted the user
    "greeted": False,
}


def load() -> dict:
    if os.path.exists(config.STATE_PATH):
        with open(config.STATE_PATH, "r", encoding="utf-8") as f:
            state = json.load(f)
        for k, v in DEFAULT_STATE.items():
            state.setdefault(k, v if not isinstance(v, (dict, list)) else type(v)(v))
        return state
    return json.loads(json.dumps(DEFAULT_STATE))


def save(state: dict) -> None:
    os.makedirs(config.DATA_DIR, exist_ok=True)
    with open(config.STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def daily_remaining(state: dict) -> int:
    """How many more videos we may summarize today under FREE_MODE."""
    if not config.FREE_MODE:
        return 10 ** 9
    today = _today()
    if state["daily"].get("date") != today:
        state["daily"] = {"date": today, "count": 0}
    return max(0, config.DAILY_VIDEO_CAP - state["daily"]["count"])


def record_summary(state: dict) -> None:
    today = _today()
    if state["daily"].get("date") != today:
        state["daily"] = {"date": today, "count": 0}
    state["daily"]["count"] += 1
