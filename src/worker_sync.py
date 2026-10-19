"""Sync command-managed channels and digest status with the Cloudflare Worker."""
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

from . import config, youtube


def _headers() -> dict:
    if not config.BOT_INTERNAL_TOKEN:
        raise RuntimeError("BOT_INTERNAL_TOKEN is not configured")
    return {
        "Authorization": f"Bearer {config.BOT_INTERNAL_TOKEN}",
        "Content-Type": "application/json",
    }


def sync_remote_channels(st: dict) -> None:
    """Worker/D1 is the source of truth for channel membership and backfill choices."""
    if not config.BOT_WORKER_URL:
        return
    base = config.BOT_WORKER_URL.rstrip("/")
    # One-time import preserves channels already tracked in data/state.json when migrating.
    bootstrap_channels = [
        {
            "channel_id": cid,
            "title": ch.get("title", cid),
            "thumb": ch.get("thumb", ""),
            "backfill": ch.get("backfill", "none"),
        }
        for cid, ch in st.get("channels", {}).items()
    ]
    bootstrap = requests.post(
        f"{base}/internal/bootstrap",
        headers=_headers(), json={"channels": bootstrap_channels}, timeout=20
    )
    bootstrap.raise_for_status()
    response = requests.get(f"{base}/internal/channels", headers=_headers(), timeout=20)
    response.raise_for_status()
    remote = response.json().get("channels", [])
    remote_by_id = {row["channel_id"]: row for row in remote}
    local_channels = st.setdefault("channels", {})
    removed = set(local_channels) - set(remote_by_id)
    for cid in removed:
        local_channels.pop(cid, None)
    if removed:
        st["queue"] = [q for q in st.get("queue", []) if q.get("channel_id") not in removed]

    queued_ids = {q.get("video_id") for q in st.get("queue", [])}
    for cid, row in remote_by_id.items():
        if cid not in local_channels:
            local_channels[cid] = {
                "title": row["title"],
                "thumb": row.get("thumb", ""),
                "added_at": "",
                "backfill": row.get("backfill", "none"),
                "seen": [],
            }
        else:
            local_channels[cid]["title"] = row["title"]
            local_channels[cid]["thumb"] = row.get("thumb", "")
            local_channels[cid]["backfill"] = row.get("backfill", "none")

        if int(row.get("initialized") or 0) == 1:
            continue

        channel = local_channels[cid]
        backfill = row.get("backfill", "none")
        if backfill == "none":
            try:
                channel["seen"] = list(dict.fromkeys(
                    channel.get("seen", []) +
                    [v["video_id"] for v in youtube.latest_from_rss(cid)]
                ))
            except Exception as exc:
                print(f"[worker-sync] Could not mark current uploads seen for {channel['title']}: {exc}")
                continue
        else:
            days = {"30d": 30, "180d": 180, "365d": 365}.get(backfill)
            if backfill == "all":
                days = None
            try:
                videos = youtube.backfill_videos(cid, days)
                for video in videos:
                    if video["video_id"] in channel.get("seen", []) or video["video_id"] in queued_ids:
                        continue
                    video["channel_id"] = cid
                    st["queue"].append(video)
                    queued_ids.add(video["video_id"])
            except Exception as exc:
                print(f"[worker-sync] Backfill failed for {channel['title']}; will retry next run: {exc}")
                continue

        mark = requests.post(
            f"{base}/internal/channels/initialized",
            headers=_headers(), json={"channel_id": cid}, timeout=20
        )
        mark.raise_for_status()
        print(f"[worker-sync] Initialized channel: {channel['title']} ({backfill})")


def publish_status(st: dict) -> None:
    if not config.BOT_WORKER_URL:
        return
    daily = st.get("daily", {})
    payload = {
        "queue": len(st.get("queue", [])),
        "daily_count": daily.get("count", 0),
        "last_run": st.get("last_run", "unknown"),
        "gemini_paused": st.get("gemini_pause_date") == datetime.now(ZoneInfo(config.TIMEZONE)).strftime("%Y-%m-%d"),
    }
    response = requests.post(
        f"{config.BOT_WORKER_URL.rstrip('/')}/internal/status",
        headers=_headers(), json=payload, timeout=20
    )
    response.raise_for_status()
