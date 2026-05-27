"""Single-video metadata lookup via the YouTube Data API v3."""
from __future__ import annotations

import os
import re

from googleapiclient.discovery import build


def _yt():
    api_key = os.getenv("YOUTUBE_API_KEY")
    if not api_key:
        raise RuntimeError("YOUTUBE_API_KEY is not set in .env")
    return build("youtube", "v3", developerKey=api_key, cache_discovery=False)


def _iso_duration_to_seconds(iso: str) -> int:
    if not iso:
        return 0
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso)
    if not m:
        return 0
    h, mi, s = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mi * 60 + s


def _format_duration(seconds: int) -> str:
    if seconds <= 0:
        return "0:00"
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fetch_video_meta(video_id: str) -> dict:
    yt = _yt()
    resp = yt.videos().list(
        part="snippet,statistics,contentDetails",
        id=video_id,
        maxResults=1,
    ).execute()

    items = resp.get("items", [])
    if not items:
        raise RuntimeError(
            f"Video {video_id!r} not found. It may be private, deleted, age-restricted, "
            "or region-blocked from your API project."
        )

    item = items[0]
    snip = item.get("snippet", {})
    stats = item.get("statistics", {})
    details = item.get("contentDetails", {})

    thumbs = snip.get("thumbnails") or {}
    thumb = (
        thumbs.get("maxres", {}).get("url")
        or thumbs.get("high", {}).get("url")
        or thumbs.get("medium", {}).get("url")
        or thumbs.get("default", {}).get("url", "")
    )

    secs = _iso_duration_to_seconds(details.get("duration", ""))

    return {
        "id": video_id,
        "title": snip.get("title", ""),
        "channel": snip.get("channelTitle", ""),
        "channel_id": snip.get("channelId", ""),
        "published_at": snip.get("publishedAt", ""),
        "thumbnail": thumb,
        "duration_iso": details.get("duration", ""),
        "duration_seconds": secs,
        "duration_label": _format_duration(secs),
        "views": int(stats.get("viewCount", 0) or 0),
        "likes": int(stats.get("likeCount", 0) or 0),
        "comments": int(stats.get("commentCount", 0) or 0),
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "description": (snip.get("description") or "")[:1500],
    }
