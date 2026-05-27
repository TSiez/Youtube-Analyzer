"""Hand a transcript to Groq and get back a structured analysis."""
from __future__ import annotations

import json
import os

try:
    from groq import Groq
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "groq is not installed. Run: pip install -r requirements.txt"
    ) from e


MODEL = "llama-3.3-70b-versatile"
MAX_TRANSCRIPT_CHARS = 32_000  # safety net; orchestrator should already have downsampled


SYSTEM_PROMPT = """You are a careful video analyst. Given a YouTube video's metadata and timestamped transcript, produce a structured JSON analysis.

Return ONLY this JSON object — no preamble, no markdown, no commentary:

{
  "summary": "2-3 sentence overview describing what the video is about and its thesis. Concrete and specific.",
  "topic_tags": ["short", "lowercase", "tags"],
  "key_moments": [
    {"timestamp": "MM:SS or HH:MM:SS", "seconds": 0, "label": "What happens at this point. Specific, not generic."}
  ],
  "highlights": [
    "Direct or near-direct quotes from the transcript that capture something memorable.",
    "..."
  ],
  "takeaways": [
    "Plain-English lessons or claims a viewer would walk away with."
  ]
}

Rules:
- Pick 4-7 key_moments distributed across the video. They must mark real inflection points (not arbitrary timecodes).
- The `seconds` field must match the `timestamp` field, derived from the transcript timestamps.
- Pick 3-5 highlights — the lines you'd quote when recommending the video.
- Pick 3-5 takeaways — the actual ideas, not vague descriptions.
- Tags should be 3-6 single words or short phrases.
- If the transcript is in a non-English language, still respond in English."""


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n\n[...transcript truncated for length...]"


def summarize_video(video_meta: dict, transcript_text: str) -> dict:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key or api_key.strip().startswith("gsk_your_"):
        raise RuntimeError("GROQ_API_KEY is not set in .env (get one at https://console.groq.com/keys).")

    client = Groq(api_key=api_key)

    user_prompt = (
        f"Video: {video_meta.get('title', '')}\n"
        f"Channel: {video_meta.get('channel', '')}\n"
        f"Duration: {video_meta.get('duration_label', '?')}\n"
        f"Views: {video_meta.get('views', 0):,}\n\n"
        f"Transcript (with timestamps):\n"
        f"{_truncate(transcript_text, MAX_TRANSCRIPT_CHARS)}"
    )

    response = client.chat.completions.create(
        model=MODEL,
        temperature=0.3,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )

    content = (response.choices[0].message.content or "").strip()
    if not content:
        raise RuntimeError("Groq returned empty content.")

    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Groq returned invalid JSON: {e}\nRaw: {content[:400]}") from e

    return _normalize(data, video_meta)


def _parse_timestamp_to_seconds(ts: str) -> int:
    parts = [int(p) for p in str(ts).split(":") if p.strip().isdigit()]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return 0


def _normalize(data: dict, video_meta: dict) -> dict:
    duration = max(1, int(video_meta.get("duration_seconds") or 1))
    out = {
        "summary": (data.get("summary") or "").strip(),
        "topic_tags": [t for t in (data.get("topic_tags") or []) if isinstance(t, str)][:8],
        "key_moments": [],
        "highlights": [h for h in (data.get("highlights") or []) if isinstance(h, str)][:8],
        "takeaways": [t for t in (data.get("takeaways") or []) if isinstance(t, str)][:8],
    }

    for km in data.get("key_moments") or []:
        if not isinstance(km, dict):
            continue
        ts = (km.get("timestamp") or "").strip()
        secs = km.get("seconds")
        if secs is None or not isinstance(secs, int):
            secs = _parse_timestamp_to_seconds(ts)
        secs = max(0, min(int(secs), duration))
        label = (km.get("label") or "").strip()
        if not label:
            continue
        out["key_moments"].append({
            "timestamp": ts or _seconds_to_timestamp(secs),
            "seconds": secs,
            "label": label,
        })

    out["key_moments"].sort(key=lambda x: x["seconds"])
    return out


def _seconds_to_timestamp(seconds: int) -> str:
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
