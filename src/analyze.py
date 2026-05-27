"""Trend analysis over fetched videos."""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from statistics import mean, median
from typing import Iterable

from .fetch import Video


STOP_WORDS = {
    "the", "a", "an", "and", "or", "but", "of", "in", "to", "for", "with", "on",
    "at", "by", "from", "is", "are", "was", "were", "be", "been", "being",
    "this", "that", "these", "those", "it", "as", "i", "you", "we", "they",
    "what", "how", "why", "when", "where", "who", "do", "does", "did", "your",
    "my", "his", "her", "our", "their", "vs", "&", "|", "best", "new", "top",
}


def _iso_duration_to_seconds(iso: str) -> int:
    if not iso:
        return 0
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso)
    if not m:
        return 0
    h, mi, s = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mi * 60 + s


def _engagement(v: Video) -> float:
    if v.views <= 0:
        return 0.0
    return (v.likes + v.comments) / v.views


def _keywords_in_titles(videos: Iterable[Video], top_n: int = 8) -> list[tuple[str, int]]:
    counter: Counter[str] = Counter()
    for v in videos:
        for token in re.findall(r"[A-Za-z0-9']+", v.title.lower()):
            if len(token) < 3 or token in STOP_WORDS:
                continue
            counter[token] += 1
    return counter.most_common(top_n)


def _format_duration(seconds: int) -> str:
    if seconds <= 0:
        return "0:00"
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


@dataclass
class ChannelStat:
    channel_title: str
    video_count: int
    total_views: int
    avg_views: float
    avg_engagement: float


@dataclass
class Report:
    generated_at: str
    lookback_days: int
    total_videos: int
    total_views: int
    median_views: int
    avg_engagement: float
    avg_duration_seconds: int
    avg_duration_label: str
    top_videos: list[Video]
    standout_videos: list[Video]
    channel_stats: list[ChannelStat]
    trending_terms: list[tuple[str, int]]
    headline: str = ""
    insights: list[str] = field(default_factory=list)
    videos: list[Video] = field(default_factory=list)


def analyze(videos: list[Video], *, lookback_days: int) -> Report:
    if not videos:
        return Report(
            generated_at=datetime.utcnow().isoformat(timespec="seconds") + "Z",
            lookback_days=lookback_days,
            total_videos=0,
            total_views=0,
            median_views=0,
            avg_engagement=0.0,
            avg_duration_seconds=0,
            avg_duration_label="0:00",
            top_videos=[],
            standout_videos=[],
            channel_stats=[],
            trending_terms=[],
            headline="No videos matched the criteria in this window.",
            insights=["Try widening the lookback or adding more channels/keywords."],
            videos=[],
        )

    total_views = sum(v.views for v in videos)
    avg_engagement = mean(_engagement(v) for v in videos)
    durations = [_iso_duration_to_seconds(v.duration) for v in videos]
    avg_duration = int(mean(durations)) if durations else 0

    top_videos = sorted(videos, key=lambda v: v.views, reverse=True)[:5]
    standout = sorted(
        [v for v in videos if v.views >= 1000],
        key=_engagement,
        reverse=True,
    )[:5] or sorted(videos, key=_engagement, reverse=True)[:5]

    by_channel: dict[str, list[Video]] = {}
    for v in videos:
        by_channel.setdefault(v.channel_title or "Unknown", []).append(v)
    channel_stats = sorted(
        [
            ChannelStat(
                channel_title=ch,
                video_count=len(vs),
                total_views=sum(v.views for v in vs),
                avg_views=mean(v.views for v in vs) if vs else 0.0,
                avg_engagement=mean(_engagement(v) for v in vs) if vs else 0.0,
            )
            for ch, vs in by_channel.items()
        ],
        key=lambda c: c.total_views,
        reverse=True,
    )

    trending_terms = _keywords_in_titles(videos)

    top = top_videos[0]
    headline = (
        f"{len(videos)} videos surfaced in the last {lookback_days} day(s); "
        f"top performer: \"{top.title[:60]}\" by {top.channel_title} ({top.views:,} views)."
    )

    insights: list[str] = []
    if channel_stats:
        leader = channel_stats[0]
        insights.append(
            f"{leader.channel_title} led with {leader.total_views:,} total views across "
            f"{leader.video_count} video(s)."
        )
    if standout:
        s = standout[0]
        insights.append(
            f"Strongest engagement: \"{s.title[:60]}\" at {_engagement(s) * 100:.2f}% (likes+comments / views)."
        )
    if trending_terms:
        words = ", ".join(w for w, _ in trending_terms[:5])
        insights.append(f"Common title themes: {words}.")
    if avg_duration:
        insights.append(f"Average video length: {_format_duration(avg_duration)}.")

    return Report(
        generated_at=datetime.utcnow().isoformat(timespec="seconds") + "Z",
        lookback_days=lookback_days,
        total_videos=len(videos),
        total_views=total_views,
        median_views=int(median(v.views for v in videos)),
        avg_engagement=avg_engagement,
        avg_duration_seconds=avg_duration,
        avg_duration_label=_format_duration(avg_duration),
        top_videos=top_videos,
        standout_videos=standout,
        channel_stats=channel_stats,
        trending_terms=trending_terms,
        headline=headline,
        insights=insights,
        videos=videos,
    )
