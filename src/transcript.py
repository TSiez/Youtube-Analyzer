"""Fetch a YouTube video's captions via youtube-transcript-api (v1.x API).

Tries preferred languages first, then falls back across available transcripts —
including auto-generated and translated ones.
"""
from __future__ import annotations

try:
    from youtube_transcript_api import (
        YouTubeTranscriptApi,
        TranscriptsDisabled,
        NoTranscriptFound,
        VideoUnavailable,
    )
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "youtube-transcript-api is not installed. Run: pip install -r requirements.txt"
    ) from e


class NoTranscriptAvailable(RuntimeError):
    """Raised when no transcript (manual, auto-generated, or translated) can be obtained."""


def _to_segments(fetched) -> list[dict]:
    """Convert FetchedTranscript → list of {start, duration, text} dicts."""
    if hasattr(fetched, "to_raw_data"):
        return list(fetched.to_raw_data())
    return [
        {"start": s.start, "duration": s.duration, "text": s.text}
        for s in fetched
    ]


def fetch_transcript(
    video_id: str,
    preferred_languages: tuple[str, ...] = ("en", "en-US", "en-GB"),
) -> list[dict]:
    """Return a list of {start, duration, text} segments sorted by start time."""
    api = YouTubeTranscriptApi()

    # 1. Direct fetch in preferred languages.
    try:
        fetched = api.fetch(video_id, languages=list(preferred_languages))
        return sorted(_to_segments(fetched), key=lambda s: s.get("start", 0))
    except (NoTranscriptFound, TranscriptsDisabled, VideoUnavailable):
        pass
    except Exception:
        pass  # fall through to listing path

    # 2. List everything, pick the best track, translate if needed.
    try:
        transcript_list = api.list(video_id)
    except (TranscriptsDisabled, VideoUnavailable) as e:
        raise NoTranscriptAvailable(
            f"This video has no captions available ({type(e).__name__})."
        ) from e
    except Exception as e:
        raise NoTranscriptAvailable(f"Could not list transcripts: {e}") from e

    manual = None
    auto = None
    for tr in transcript_list:
        if not tr.is_generated and manual is None:
            manual = tr
        elif tr.is_generated and auto is None:
            auto = tr

    pick = manual or auto
    if pick is None:
        raise NoTranscriptAvailable("No transcript tracks were returned for this video.")

    try:
        if pick.language_code not in preferred_languages and pick.is_translatable:
            try:
                translated = pick.translate("en")
                fetched = translated.fetch()
            except Exception:
                fetched = pick.fetch()
        else:
            fetched = pick.fetch()
        return sorted(_to_segments(fetched), key=lambda s: s.get("start", 0))
    except Exception as e:
        raise NoTranscriptAvailable(f"Could not fetch the available transcript: {e}") from e


def format_timestamp(seconds: float) -> str:
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{sec:02d}"
    return f"{m:02d}:{sec:02d}"


def format_with_timestamps(segments: list[dict]) -> str:
    lines = []
    for s in segments:
        ts = format_timestamp(s.get("start", 0))
        text = (s.get("text") or "").replace("\n", " ").strip()
        if text:
            lines.append(f"[{ts}] {text}")
    return "\n".join(lines)


def downsample_segments(segments: list[dict], char_budget: int = 28_000) -> list[dict]:
    """Uniformly subsample so the formatted transcript fits under the char budget.

    Preserves coverage across the whole video — taking every Nth segment —
    rather than truncating to just the start. Headers/footers stay representative.
    """
    if not segments:
        return segments
    text_len = len(format_with_timestamps(segments))
    if text_len <= char_budget:
        return segments
    ratio = text_len / char_budget
    keep_every = max(1, int(ratio + 0.99))
    return segments[::keep_every]
