"""YouTube helpers.

Polling for NEW videos uses the official RSS feed (free, no key, no bot walls).
Handle resolution and historical backfill use the YouTube Data API v3
(free quota: 10,000 units/day; a full backfill of a large channel costs <50).
"""
import re
from datetime import datetime, timedelta, timezone

import feedparser
import requests

from . import config

RSS_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={cid}"
API = "https://www.googleapis.com/youtube/v3"


def resolve_channel(query: str) -> dict | None:
    """Accepts @handle, channel URL, video URL, or plain channel id.
    Returns {channel_id, title, thumb} or None."""
    query = query.strip()

    m = re.search(r"(UC[0-9A-Za-z_-]{22})", query)
    if m:
        return _channel_by_id(m.group(1))

    m = re.search(r"youtube\.com/@([\w.\-]+)", query) or re.match(r"^@?([\w.\-]+)$", query)
    if m:
        handle = m.group(1)
        r = requests.get(f"{API}/channels", params={
            "part": "snippet", "forHandle": handle, "key": config.YOUTUBE_API_KEY,
        }, timeout=30)
        r.raise_for_status()
        items = r.json().get("items", [])
        if items:
            return _pack(items[0])

    # Last resort: search
    r = requests.get(f"{API}/search", params={
        "part": "snippet", "q": query, "type": "channel", "maxResults": 1,
        "key": config.YOUTUBE_API_KEY,
    }, timeout=30)
    r.raise_for_status()
    items = r.json().get("items", [])
    if items:
        return _channel_by_id(items[0]["snippet"]["channelId"])
    return None


def _channel_by_id(cid: str) -> dict | None:
    r = requests.get(f"{API}/channels", params={
        "part": "snippet", "id": cid, "key": config.YOUTUBE_API_KEY,
    }, timeout=30)
    r.raise_for_status()
    items = r.json().get("items", [])
    return _pack(items[0]) if items else None


def _pack(item: dict) -> dict:
    sn = item["snippet"]
    thumbs = sn.get("thumbnails", {})
    thumb = (thumbs.get("medium") or thumbs.get("default") or {}).get("url", "")
    return {"channel_id": item["id"], "title": sn["title"], "thumb": thumb}


def latest_from_rss(channel_id: str) -> list[dict]:
    """Latest ~15 uploads, newest first. No API key needed."""
    feed = feedparser.parse(RSS_URL.format(cid=channel_id))
    out = []
    for e in feed.entries:
        vid = getattr(e, "yt_videoid", None)
        if not vid:
            continue
        out.append({
            "video_id": vid,
            "title": e.title,
            "published": e.published,  # ISO 8601
            "url": f"https://www.youtube.com/watch?v={vid}",
        })
    return out


def backfill_videos(channel_id: str, days: int | None) -> list[dict]:
    """All uploads within the window (days=None -> full history), oldest first."""
    uploads_playlist = "UU" + channel_id[2:]
    cutoff = None
    if days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    videos, page = [], None
    while True:
        params = {
            "part": "snippet,contentDetails", "playlistId": uploads_playlist,
            "maxResults": 50, "key": config.YOUTUBE_API_KEY,
        }
        if page:
            params["pageToken"] = page
        r = requests.get(f"{API}/playlistItems", params=params, timeout=30)
        if r.status_code == 404:
            break
        r.raise_for_status()
        data = r.json()
        stop = False
        for it in data.get("items", []):
            pub = it["contentDetails"].get("videoPublishedAt") or it["snippet"]["publishedAt"]
            dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
            if cutoff and dt < cutoff:
                stop = True
                continue  # playlist is newest-first; keep scanning page then stop
            videos.append({
                "video_id": it["contentDetails"]["videoId"],
                "title": it["snippet"]["title"],
                "published": pub,
                "url": "https://www.youtube.com/watch?v=" + it["contentDetails"]["videoId"],
            })
        page = data.get("nextPageToken")
        if not page or stop:
            break
    videos.sort(key=lambda v: v["published"])  # oldest first, so the tree grows chronologically
    return videos
