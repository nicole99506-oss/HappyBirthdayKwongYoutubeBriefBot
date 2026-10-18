"""Runtime configuration. Secrets are supplied via GitHub Actions."""
import os

APP_NAME = "Happy Birthday Kwong"

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")

ALLOWED_CHAT_IDS = [
    c.strip() for c in os.environ.get(
        "ALLOWED_CHAT_IDS", TELEGRAM_CHAT_ID
    ).split(",") if c.strip()
]

# Use a lightweight model by default. Override via GitHub Actions variable
# GEMINI_MODEL only if this model is unavailable for your account.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "").strip() or "gemini-2.5-flash-lite"

# Conservative free-usage guardrails: one video per run and four per local day.
FREE_MODE = os.environ.get("FREE_MODE", "true").lower() != "false"
MAX_VIDEOS_PER_RUN = int(os.environ.get("MAX_VIDEOS_PER_RUN", "1"))
DAILY_VIDEO_CAP = int(os.environ.get("DAILY_VIDEO_CAP", "4"))
MIN_HOURS_BETWEEN_GEMINI_REQUESTS = int(os.environ.get("MIN_HOURS_BETWEEN_GEMINI_REQUESTS", "6"))

DATA_DIR = "data"
STATE_PATH = os.path.join(DATA_DIR, "state.json")
TIMEZONE = "Asia/Singapore"

# (label, callback code, days back; None = full history, 0 = new videos only)
BACKFILL_OPTIONS = [
    ("Full history", "all", None),
    ("Last 30 days", "30d", 30),
    ("Last 6 months", "180d", 180),
    ("Last 12 months", "365d", 365),
    ("New videos only", "none", 0),
]
