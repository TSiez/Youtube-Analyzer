"""Generate a styled Google Slides deck from the analyzed report.

On first run, creates a deck and writes PRESENTATION_ID back to .env.
On subsequent runs, clears existing slides on the same deck and rewrites them.
"""
from __future__ import annotations

from datetime import datetime
from typing import Callable

from googleapiclient.discovery import build

from .analyze import Report
from .auth import get_credentials
from .config import Config, write_env_value


BRAND_INDIGO = {"red": 0.31, "green": 0.275, "blue": 0.898}     # #4f46e5
BRAND_INK = {"red": 0.06, "green": 0.09, "blue": 0.16}           # #0f172a
BRAND_MUTED = {"red": 0.42, "green": 0.45, "blue": 0.50}         # #6b7280
BRAND_TINT = {"red": 0.93, "green": 0.95, "blue": 1.00}          # #eef2ff
WHITE = {"red": 1, "green": 1, "blue": 1}


def _slides_client():
    creds = get_credentials()
    return build("slides", "v1", credentials=creds, cache_discovery=False)


def _next_id_factory():
    counter = {"n": 0}

    def gen(prefix: str) -> str:
        counter["n"] += 1
        return f"{prefix}_{counter['n']:04d}"

    return gen


def _ensure_presentation(svc, cfg: Config, log: Callable[[str], None]) -> str:
    if cfg.presentation_id:
        log(f"[slides] reusing presentation {cfg.presentation_id}")
        return cfg.presentation_id

    log("[slides] no PRESENTATION_ID — creating a new deck")
    pres = svc.presentations().create(
        body={"title": "YouTube Analyst — Weekly Report"}
    ).execute()
    pid = pres["presentationId"]
    log(f"[slides] created deck {pid}")
    write_env_value("PRESENTATION_ID", pid)
    log("[slides] saved PRESENTATION_ID to .env")
    cfg.presentation_id = pid
    return pid


def _clear_existing_slides(svc, presentation_id: str) -> None:
    pres = svc.presentations().get(presentationId=presentation_id).execute()
    slides = pres.get("slides", [])
    if len(slides) <= 1:
        return
    requests = [{"deleteObject": {"objectId": s["objectId"]}} for s in slides[1:]]
    svc.presentations().batchUpdate(
        presentationId=presentation_id, body={"requests": requests}
    ).execute()


def _text_style(object_id: str, text: str, *,
                font_size_pt: float = 14,
                bold: bool = False,
                color: dict | None = None) -> list[dict]:
    reqs: list[dict] = [
        {"insertText": {"objectId": object_id, "insertionIndex": 0, "text": text}}
    ]
    style: dict = {
        "fontSize": {"magnitude": font_size_pt, "unit": "PT"},
        "bold": bold,
    }
    if color:
        style["foregroundColor"] = {"opaqueColor": {"rgbColor": color}}
    reqs.append({
        "updateTextStyle": {
            "objectId": object_id,
            "textRange": {"type": "ALL"},
            "style": style,
            "fields": "fontSize,bold" + (",foregroundColor" if color else ""),
        }
    })
    return reqs


def _shape(object_id: str, slide_id: str, *,
           x: float, y: float, w: float, h: float,
           fill_color: dict | None = None) -> list[dict]:
    reqs: list[dict] = [{
        "createShape": {
            "objectId": object_id,
            "shapeType": "TEXT_BOX",
            "elementProperties": {
                "pageObjectId": slide_id,
                "size": {
                    "width": {"magnitude": w, "unit": "PT"},
                    "height": {"magnitude": h, "unit": "PT"},
                },
                "transform": {
                    "scaleX": 1, "scaleY": 1, "translateX": x, "translateY": y, "unit": "PT",
                },
            },
        }
    }]
    if fill_color:
        reqs.append({
            "updateShapeProperties": {
                "objectId": object_id,
                "shapeProperties": {
                    "shapeBackgroundFill": {
                        "solidFill": {"color": {"rgbColor": fill_color}}
                    }
                },
                "fields": "shapeBackgroundFill.solidFill.color",
            }
        })
    return reqs


def _make_slide(slide_id: str) -> dict:
    return {
        "createSlide": {
            "objectId": slide_id,
            "slideLayoutReference": {"predefinedLayout": "BLANK"},
        }
    }


def _build_cover_slide(report: Report, slide_id: str, gen) -> list[dict]:
    reqs: list[dict] = [_make_slide(slide_id)]

    accent_id = gen("cover_accent")
    reqs += _shape(accent_id, slide_id, x=0, y=0, w=720, h=110, fill_color=BRAND_INDIGO)

    eyebrow_id = gen("cover_eyebrow")
    reqs += _shape(eyebrow_id, slide_id, x=48, y=30, w=400, h=18)
    reqs += _text_style(eyebrow_id, "YOUTUBE ANALYST — WEEKLY REPORT",
                        font_size_pt=10, bold=True, color=WHITE)

    title_id = gen("cover_title")
    reqs += _shape(title_id, slide_id, x=48, y=55, w=624, h=46)
    reqs += _text_style(title_id, "Trends, Standouts & Themes",
                        font_size_pt=28, bold=True, color=WHITE)

    headline_id = gen("cover_headline")
    reqs += _shape(headline_id, slide_id, x=48, y=140, w=624, h=80)
    reqs += _text_style(headline_id, report.headline, font_size_pt=18, color=BRAND_INK)

    date_id = gen("cover_date")
    reqs += _shape(date_id, slide_id, x=48, y=370, w=400, h=20)
    nice_date = datetime.utcnow().strftime("Generated %B %d, %Y · UTC")
    reqs += _text_style(date_id, nice_date, font_size_pt=11, color=BRAND_MUTED)

    return reqs


def _build_metrics_slide(report: Report, slide_id: str, gen) -> list[dict]:
    reqs: list[dict] = [_make_slide(slide_id)]

    title_id = gen("m_title")
    reqs += _shape(title_id, slide_id, x=48, y=36, w=624, h=30)
    reqs += _text_style(title_id, "Key metrics", font_size_pt=20, bold=True, color=BRAND_INK)

    metrics = [
        ("Videos analyzed", f"{report.total_videos}"),
        ("Total views", f"{report.total_views:,}"),
        ("Median views", f"{report.median_views:,}"),
        ("Avg engagement", f"{report.avg_engagement * 100:.2f}%"),
        ("Avg duration", report.avg_duration_label),
        ("Lookback window", f"{report.lookback_days} days"),
    ]

    card_w, card_h = 196, 96
    gap = 18
    start_x, start_y = 48, 96
    for idx, (label, value) in enumerate(metrics):
        col = idx % 3
        row = idx // 3
        x = start_x + col * (card_w + gap)
        y = start_y + row * (card_h + gap)

        card_id = gen("m_card")
        reqs += _shape(card_id, slide_id, x=x, y=y, w=card_w, h=card_h, fill_color=BRAND_TINT)

        label_id = gen("m_label")
        reqs += _shape(label_id, slide_id, x=x + 14, y=y + 14, w=card_w - 28, h=14)
        reqs += _text_style(label_id, label.upper(), font_size_pt=9, bold=True, color=BRAND_MUTED)

        value_id = gen("m_value")
        reqs += _shape(value_id, slide_id, x=x + 14, y=y + 34, w=card_w - 28, h=44)
        reqs += _text_style(value_id, value, font_size_pt=22, bold=True, color=BRAND_INK)

    return reqs


def _build_text_slide(slide_id: str, title: str, lines: list[str], gen,
                      max_lines: int = 12) -> list[dict]:
    reqs: list[dict] = [_make_slide(slide_id)]

    title_id = gen("t_title")
    reqs += _shape(title_id, slide_id, x=48, y=36, w=624, h=30)
    reqs += _text_style(title_id, title, font_size_pt=20, bold=True, color=BRAND_INK)

    body_id = gen("t_body")
    reqs += _shape(body_id, slide_id, x=48, y=84, w=624, h=300)
    body_text = "\n".join(f"•  {line}" for line in lines[:max_lines]) or "—"
    reqs += _text_style(body_id, body_text, font_size_pt=14, color=BRAND_INK)

    return reqs


def write_deck(cfg: Config, report: Report, log: Callable[[str], None] = print) -> str:
    svc = _slides_client()
    presentation_id = _ensure_presentation(svc, cfg, log)

    log("[slides] clearing existing slides (if any)")
    _clear_existing_slides(svc, presentation_id)

    gen = _next_id_factory()
    requests: list[dict] = []

    requests += _build_cover_slide(report, gen("slide_cover"), gen)
    requests += _build_metrics_slide(report, gen("slide_metrics"), gen)

    top_lines = [
        f"{v.title[:70]} — {v.channel_title} · {v.views:,} views"
        for v in report.top_videos
    ]
    requests += _build_text_slide(gen("slide_top"), "Top videos (by views)", top_lines, gen)

    standout_lines = [
        f"{v.title[:70]} — {v.channel_title} · "
        f"{((v.likes + v.comments) / max(v.views, 1)) * 100:.2f}% engagement"
        for v in report.standout_videos
    ]
    requests += _build_text_slide(gen("slide_standout"), "Standout engagement", standout_lines, gen)

    requests += _build_text_slide(
        gen("slide_insights"),
        "Insights",
        report.insights or ["No notable insights this week."],
        gen,
    )

    theme_lines = [f"{w} — mentioned in {n} title(s)" for w, n in report.trending_terms]
    requests += _build_text_slide(gen("slide_themes"), "Trending title themes", theme_lines, gen)

    channel_lines = [
        f"{c.channel_title} · {c.total_views:,} total views · "
        f"{c.video_count} video(s) · {c.avg_engagement * 100:.2f}% avg engagement"
        for c in report.channel_stats[:8]
    ]
    requests += _build_text_slide(gen("slide_channels"), "By channel", channel_lines, gen)

    log(f"[slides] sending {len(requests)} batch requests")
    for i in range(0, len(requests), 200):
        chunk = requests[i : i + 200]
        svc.presentations().batchUpdate(
            presentationId=presentation_id, body={"requests": chunk}
        ).execute()

    url = f"https://docs.google.com/presentation/d/{presentation_id}/edit"
    log(f"[slides] deck ready: {url}")
    return url
