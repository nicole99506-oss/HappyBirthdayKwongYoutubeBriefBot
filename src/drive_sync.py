"""Sync summaries to Google Drive as Google Docs (NotebookLM-friendly).

Layout inside the shared folder:
  <root>/
    _START HERE — NotebookLM Prompt          (English how-to + ready-made prompt)
    <Channel Name>/
      _NotebookLM Pack — <Channel Name>      (all summaries, one doc, kept fresh)
      YYYY-MM-DD — <Video title>             (one doc per video)

Markdown is uploaded with Drive's convert-to-Google-Doc so NotebookLM's Drive
picker can select everything directly.
"""
import json

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload

from . import config

_service = None
DOC_MIME = "application/vnd.google-apps.document"
FOLDER_MIME = "application/vnd.google-apps.folder"


def enabled() -> bool:
    return bool(config.GDRIVE_SERVICE_ACCOUNT_JSON and config.GDRIVE_FOLDER_ID)


def service():
    global _service
    if _service is None:
        info = json.loads(config.GDRIVE_SERVICE_ACCOUNT_JSON)
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/drive"])
        _service = build("drive", "v3", credentials=creds, cache_discovery=False)
    return _service


def _find(name: str, parent: str, mime: str | None = None) -> str | None:
    safe = name.replace("'", "\\'")
    q = f"name = '{safe}' and '{parent}' in parents and trashed = false"
    if mime:
        q += f" and mimeType = '{mime}'"
    res = service().files().list(q=q, fields="files(id)", pageSize=1,
                                 supportsAllDrives=True,
                                 includeItemsFromAllDrives=True).execute()
    files = res.get("files", [])
    return files[0]["id"] if files else None


def ensure_folder(name: str) -> str:
    fid = _find(name, config.GDRIVE_FOLDER_ID, FOLDER_MIME)
    if fid:
        return fid
    meta = {"name": name, "mimeType": FOLDER_MIME, "parents": [config.GDRIVE_FOLDER_ID]}
    return service().files().create(body=meta, fields="id",
                                    supportsAllDrives=True).execute()["id"]


def upsert_doc(name: str, markdown: str, parent: str) -> None:
    """Create or update a Google Doc converted from markdown.
    Falls back to a plain .md file if conversion is unavailable."""
    media = MediaInMemoryUpload(markdown.encode("utf-8"), mimetype="text/markdown",
                                resumable=False)
    existing = _find(name, parent)
    try:
        if existing:
            service().files().update(fileId=existing, media_body=media,
                                     supportsAllDrives=True).execute()
        else:
            meta = {"name": name, "mimeType": DOC_MIME, "parents": [parent]}
            service().files().create(body=meta, media_body=media, fields="id",
                                     supportsAllDrives=True).execute()
    except Exception:
        meta = {"name": name + ".md", "parents": [parent]}
        service().files().create(body=meta, media_body=media, fields="id",
                                 supportsAllDrives=True).execute()


# ---------------------------------------------------------------------------
# NotebookLM helper docs (English, ready to copy-paste)
# ---------------------------------------------------------------------------

START_HERE = """# How to load this library into NotebookLM

1. Open notebooklm.google.com and create a notebook (one per channel works best).
2. Click **Add source → Google Drive**, then pick either:
   - the single doc "_NotebookLM Pack — <channel>" (fastest, always up to date), or
   - the individual video docs in that channel's folder (finer-grained citations).
3. Paste the prompt below into the NotebookLM chat to kick off a synthesis.

---

## Copy-paste prompt

You have been given briefing summaries of videos from a YouTube channel covering
global political economy. Each briefing contains a TL;DR, a summary, highlights,
key concepts, and a "why it matters" note. Please:

1. Build a thematic map of this channel's worldview: what are its 4-6 recurring
   theses, and how has each evolved across the briefings (cite dates)?
2. List the analytical frameworks and key concepts the channel relies on, with a
   one-line explanation of each and where it was introduced.
3. Identify where the channel's predictions or claims conflict with each other
   over time, or with mainstream consensus.
4. Finish with the 5 open questions I should watch for in upcoming videos.

Be specific, cite the source briefings, and keep the whole answer under 800 words.
"""


def sync_start_here() -> None:
    upsert_doc("_START HERE — NotebookLM Prompt", START_HERE, config.GDRIVE_FOLDER_ID)


def build_pack(channel_title: str, entries: list[dict]) -> str:
    """entries: [{title, published, url, markdown}] sorted oldest->newest."""
    head = [
        f"# NotebookLM Pack — {channel_title}",
        "",
        f"All video briefings from **{channel_title}**, oldest to newest. "
        "Add this single doc as a NotebookLM source and it stays current — "
        "the system refreshes it after every new video.",
        "",
        "---",
        "",
    ]
    body = []
    for e in entries:
        body.append(e["markdown"])
        body.append("\n---\n")
    return "\n".join(head) + "\n".join(body)


def sync_channel(channel_title: str, entries: list[dict], latest: dict | None) -> None:
    """Upload the latest per-video doc and refresh the channel pack."""
    folder = ensure_folder(channel_title)
    if latest is not None:
        name = f"{latest['published'][:10]} — {latest['title'][:80]}"
        upsert_doc(name, latest["markdown"], folder)
    upsert_doc(f"_NotebookLM Pack — {channel_title}",
               build_pack(channel_title, entries), folder)
