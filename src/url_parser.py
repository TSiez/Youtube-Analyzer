"""Extract a YouTube video ID from any of the common URL shapes."""
from __future__ import annotations

import re

_PATTERNS = [
    re.compile(r"(?:youtube\.com/watch\?(?:[^&]+&)*v=)([a-zA-Z0-9_-]{11})"),
    re.compile(r"(?:youtu\.be/)([a-zA-Z0-9_-]{11})"),
    re.compile(r"(?:youtube\.com/embed/)([a-zA-Z0-9_-]{11})"),
    re.compile(r"(?:youtube\.com/shorts/)([a-zA-Z0-9_-]{11})"),
    re.compile(r"(?:youtube\.com/v/)([a-zA-Z0-9_-]{11})"),
    re.compile(r"(?:youtube\.com/live/)([a-zA-Z0-9_-]{11})"),
    re.compile(r"^([a-zA-Z0-9_-]{11})$"),  # bare ID
]


def extract_video_id(url_or_id: str) -> str:
    raw = (url_or_id or "").strip()
    if not raw:
        raise ValueError("No URL provided.")
    for pat in _PATTERNS:
        m = pat.search(raw)
        if m:
            return m.group(1)
    raise ValueError(
        f"Could not extract a YouTube video ID from: {raw!r}. "
        "Expected something like https://www.youtube.com/watch?v=… or https://youtu.be/…"
    )
