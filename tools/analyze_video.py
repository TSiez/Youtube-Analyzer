"""URL-mode orchestrator: one YouTube URL in → structured analysis out.

Usage:
    python tools/analyze_video.py --url https://www.youtube.com/watch?v=...
    python tools/analyze_video.py --url https://youtu.be/...

Streams [stage] lines to stdout for live UI display, then emits a single
`RESULT: <json>` line that the dashboard parses to render the result panel.
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

# Force UTF-8 on stdout/stderr so emoji and special chars in LLM output don't crash
# the script on Windows (default cp1252).
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from googleapiclient.errors import HttpError  # noqa: E402

from src.url_parser import extract_video_id  # noqa: E402
from src.video_meta import fetch_video_meta  # noqa: E402
from src.transcript import (  # noqa: E402
    fetch_transcript,
    format_with_timestamps,
    downsample_segments,
    NoTranscriptAvailable,
)
from src.summarize import summarize_video  # noqa: E402


def log(msg: str) -> None:
    print(msg, flush=True)


def emit_result(payload: dict) -> None:
    print("RESULT: " + json.dumps(payload, ensure_ascii=False), flush=True)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Analyze one YouTube video.")
    p.add_argument("--url", required=True, help="YouTube URL or 11-char video ID")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    log("[pipeline] step 1/4 — parse URL")
    try:
        video_id = extract_video_id(args.url)
    except ValueError as e:
        log(f"ERROR: {e}")
        return 2
    log(f"[parse] video id: {video_id}")

    log("[pipeline] step 2/4 — fetch video metadata")
    try:
        meta = fetch_video_meta(video_id)
    except HttpError as e:
        log(f"ERROR (YouTube API): {e}")
        if "quota" in str(e).lower():
            log("Hint: you may have exhausted the YouTube Data API daily quota.")
        return 3
    except RuntimeError as e:
        log(f"ERROR: {e}")
        return 3
    log(f"[meta] {meta['title']!r} — {meta['channel']} · {meta['duration_label']} · {meta['views']:,} views")

    log("[pipeline] step 3/4 — fetch transcript")
    transcript_text = ""
    transcript_available = False
    try:
        segments = fetch_transcript(video_id)
        original_count = len(segments)
        segments = downsample_segments(segments, char_budget=28_000)
        if len(segments) < original_count:
            log(f"[transcript] downsampled {original_count} -> {len(segments)} segments to fit LLM budget")
        transcript_text = format_with_timestamps(segments)
        transcript_available = True
        log(f"[transcript] {len(segments)} segment(s) · {len(transcript_text):,} chars")
    except NoTranscriptAvailable as e:
        log(f"[transcript] WARN no captions: {e}")
        log("[transcript] falling back to title + description for summarization")
        transcript_text = (
            f"NOTE: Captions are unavailable. Analyze from metadata alone.\n\n"
            f"Title: {meta['title']}\n"
            f"Channel: {meta['channel']}\n"
            f"Description:\n{meta.get('description', '')}"
        )

    log("[pipeline] step 4/4 — summarize via Groq")
    try:
        analysis = summarize_video(meta, transcript_text)
    except RuntimeError as e:
        log(f"ERROR: {e}")
        return 4
    log(
        f"[summarize] {len(analysis['key_moments'])} key moment(s), "
        f"{len(analysis['highlights'])} highlight(s), "
        f"{len(analysis['takeaways'])} takeaway(s)"
    )

    result = {
        "video": meta,
        "transcript_available": transcript_available,
        **analysis,
    }
    emit_result(result)
    log("[pipeline] DONE")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log("[pipeline] interrupted by user")
        sys.exit(130)
    except Exception as e:
        log(f"[pipeline] FATAL: {e}")
        log(traceback.format_exc())
        sys.exit(1)
