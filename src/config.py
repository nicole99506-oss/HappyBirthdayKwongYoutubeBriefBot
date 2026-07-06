"""Central configuration for Happy Birthday Kwong.

All secrets come from environment variables (GitHub Actions secrets).
Everything here is tuned so the system runs at $0 cost by default.
"""
import os

APP_NAME = "Happy Birthday Kwong"

# --- Secrets (set in GitHub repo Settings -> Secrets and variables -> Actions) ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")           # where digests are delivered
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")             # free, for backfill + handle lookup
GDRIVE_SERVICE_ACCOUNT_JSON = os.environ.get("GDRIVE_SERVICE_ACCOUNT_JSON", "")
GDRIVE_FOLDER_ID = os.environ.get("GDRIVE_FOLDER_ID", "")

# Optional: comma-separated chat ids allowed to manage channels (defaults to TELEGRAM_CHAT_ID)
ALLOWED_CHAT_IDS = [
    c.strip() for c in os.environ.get("ALLOWED_CHAT_IDS", TELEGRAM_CHAT_ID).split(",") if c.strip()
]

# --- Model ---
# Override with the GEMINI_MODEL repo variable if Google renames models.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

# --- Free-mode guardrails ---------------------------------------------------
# FREE_MODE=true (default) keeps the system inside Gemini's free tier:
#   * at most MAX_VIDEOS_PER_RUN summaries per workflow run
#   * at most DAILY_VIDEO_CAP summaries per calendar day (HKT)
# Videos above the cap stay in the queue and are processed on later runs/days.
# If the API ever returns a quota error we stop, notify via Telegram, and retry
# next run. With no billing account attached to the Gemini key, Google cannot
# charge anything -- requests over quota simply fail.
FREE_MODE = os.environ.get("FREE_MODE", "true").lower() != "false"
MAX_VIDEOS_PER_RUN = int(os.environ.get("MAX_VIDEOS_PER_RUN", "6"))
DAILY_VIDEO_CAP = int(os.environ.get("DAILY_VIDEO_CAP", "20"))

# Mind map: consolidate the tree when it grows beyond this many nodes
MINDMAP_MAX_NODES = int(os.environ.get("MINDMAP_MAX_NODES", "60"))

# --- Paths ---
DATA_DIR = "data"
STATE_PATH = os.path.join(DATA_DIR, "state.json")
SUMMARY_DIR = os.path.join(DATA_DIR, "summaries")
MINDMAP_DIR = os.path.join(DATA_DIR, "mindmaps")
DOCS_DIR = "docs"

TIMEZONE = "Asia/Hong_Kong"

# Backfill options shown as inline buttons when a channel is added.
# (label, callback code, days back; None = unlimited, 0 = new videos only)
BACKFILL_OPTIONS = [
    ("Full history", "all", None),
    ("Last 30 days", "30d", 30),
    ("Last 6 months", "180d", 180),
    ("Last 12 months", "365d", 365),
    ("New videos only", "none", 0),
]
