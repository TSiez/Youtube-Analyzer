"""YouTube Data API v3 — fetch recent video data for channels and keywords."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from typing import Iterable

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


@dataclass
class Video:
    video_id: str
    title: str
    channel_id: str
    channel_title: str
    published_at: str
    source_type: str        # "channel" or "keyword"
    source_value: str       # the channel handle/id or the keyword that surfaced it
    views: int = 0
    likes: int = 0
    comments: int = 0
    duration: str = ""      # ISO 8601 duration like PT5M32S
    thumbnail: str = ""

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.video_id}"


def _yt_client(api_key: str):
    return build("youtube", "v3", developerKey=api_key, cache_discovery=False)


def _published_after(lookback_days: int) -> str:
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    return cutoff.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _resolve_channel_id(yt, handle_or_id: str) -> tuple[str, str] | None:
    """Accept either a channel ID (starts with UC) or a handle like '@mkbhd'.
    Returns (channel_id, channel_title) or None."""
    raw = handle_or_id.strip()
    if not raw:
        return None

    if raw.startswith("UC") and len(raw) > 10 and " " not in raw:
        resp = yt.channels().list(part="snippet", id=raw, maxResults=1).execute()
        items = resp.get("items", [])
        if items:
            return items[0]["id"], items[0]["snippet"]["title"]

    handle = raw if raw.startswith("@") else f"@{raw}"
    resp = yt.channels().list(part="snippet", forHandle=handle, maxResults=1).execute()
    items = resp.get("items", [])
    if items:
        return items[0]["id"], items[0]["snippet"]["title"]

    resp = yt.search().list(part="snippet", q=raw, type="channel", maxResults=1).execute()
    items = resp.get("items", [])
    if items:
        return items[0]["snippet"]["channelId"], items[0]["snippet"]["channelTitle"]
    return None


def _search_videos(yt, *, query: str | None = None, channel_id: str | None = None,
                   max_results: int, published_after: str) -> list[dict]:
    params = dict(
        part="snippet",
        type="video",
        order="viewCount",
        publishedAfter=published_after,
        maxResults=min(max_results, 50),
    )
    if query:
        params["q"] = query
    if channel_id:
        params["channelId"] = channel_id

    resp = yt.search().list(**params).execute()
    return resp.get("items", [])


def _hydrate_stats(yt, video_ids: list[str]) -> dict[str, dict]:
    """Fetch statistics + contentDetails for a batch of video IDs."""
    if not video_ids:
        return {}
    by_id: dict[str, dict] = {}
    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i : i + 50]
        resp = yt.videos().list(
            part="statistics,contentDetails,snippet",
            id=",".join(chunk),
            maxResults=50,
        ).execute()
        for item in resp.get("items", []):
            by_id[item["id"]] = item
    return by_id


def fetch_videos(
    *,
    api_key: str,
    channels: Iterable[str],
    keywords: Iterable[str],
    lookback_days: int,
    max_results: int,
    log=print,
) -> list[Video]:
    """Fetch recent (last `lookback_days`) videos from each channel and for each keyword.

    `log` is a printable callable so the orchestrator/server can stream progress.
    """
    if not api_key:
        raise RuntimeError("YOUTUBE_API_KEY is required for fetch_videos().")

    yt = _yt_client(api_key)
    published_after = _published_after(lookback_days)
    log(f"[fetch] window: last {lookback_days} day(s) (since {published_after})")

    raw_items: list[tuple[str, str, dict]] = []  # (source_type, source_value, search_item)

    for channel_hint in channels:
        try:
            resolved = _resolve_channel_id(yt, channel_hint)
        except HttpError as e:
            log(f"[fetch] WARN resolving '{channel_hint}': {e}")
            continue
        if not resolved:
            log(f"[fetch] WARN could not resolve channel '{channel_hint}'")
            continue
        channel_id, channel_title = resolved
        log(f"[fetch] channel: {channel_title} ({channel_id})")
        try:
            items = _search_videos(
                yt,
                channel_id=channel_id,
                max_results=max_results,
                published_after=published_after,
            )
        except HttpError as e:
            log(f"[fetch] WARN searching channel {channel_title}: {e}")
            continue
        for item in items:
            raw_items.append(("channel", channel_title, item))

    for keyword in keywords:
        log(f"[fetch] keyword: {keyword}")
        try:
            items = _search_videos(
                yt,
                query=keyword,
                max_results=max_results,
                published_after=published_after,
            )
        except HttpError as e:
            log(f"[fetch] WARN searching keyword {keyword}: {e}")
            continue
        for item in items:
            raw_items.append(("keyword", keyword, item))

    video_ids: list[str] = []
    seen: set[str] = set()
    for _, _, item in raw_items:
        vid_id = item.get("id", {}).get("videoId")
        if vid_id and vid_id not in seen:
            seen.add(vid_id)
            video_ids.append(vid_id)

    log(f"[fetch] hydrating stats for {len(video_ids)} unique video(s)")
    stats_by_id = _hydrate_stats(yt, video_ids)

    videos: list[Video] = []
    added: set[str] = set()
    for source_type, source_value, item in raw_items:
        vid_id = item.get("id", {}).get("videoId")
        if not vid_id or vid_id in added:
            continue
        added.add(vid_id)
        stat_item = stats_by_id.get(vid_id, {})
        snip = stat_item.get("snippet") or item.get("snippet", {})
        stats = stat_item.get("statistics", {})
        details = stat_item.get("contentDetails", {})
        thumb = (snip.get("thumbnails") or {}).get("medium", {}).get("url", "")
        videos.append(
            Video(
                video_id=vid_id,
                title=snip.get("title", ""),
                channel_id=snip.get("channelId", ""),
                channel_title=snip.get("channelTitle", ""),
                published_at=snip.get("publishedAt", ""),
                source_type=source_type,
                source_value=source_value,
                views=int(stats.get("viewCount", 0) or 0),
                likes=int(stats.get("likeCount", 0) or 0),
                comments=int(stats.get("commentCount", 0) or 0),
                duration=details.get("duration", ""),
                thumbnail=thumb,
            )
        )

    log(f"[fetch] returning {len(videos)} video(s)")
    return videos


def videos_to_dicts(videos: Iterable[Video]) -> list[dict]:
    return [asdict(v) | {"url": v.url} for v in videos]
