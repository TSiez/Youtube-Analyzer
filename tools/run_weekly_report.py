"""Entry point: run the full weekly pipeline.

Usage:
    python tools/run_weekly_report.py
    python tools/run_weekly_report.py --channels "@mkbhd,@verge" --keywords "ai,robots"
    python tools/run_weekly_report.py --skip-email           # generate report but don't send
    python tools/run_weekly_report.py --no-slides --no-sheets   # disable individual steps
"""
from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

# Make the project root importable when running this file directly.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from googleapiclient.errors import HttpError  # noqa: E402

from src.analyze import analyze  # noqa: E402
from src.config import Config  # noqa: E402
from src.fetch import fetch_videos  # noqa: E402


def log(msg: str) -> None:
    print(msg, flush=True)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run the YouTube Analyst weekly pipeline.")
    p.add_argument("--channels", help="Override YT_CHANNELS (comma-separated handles or IDs)")
    p.add_argument("--keywords", help="Override YT_KEYWORDS (comma-separated terms)")
    p.add_argument("--lookback", type=int, help="Override LOOKBACK_DAYS")
    p.add_argument("--max-results", type=int, help="Override MAX_RESULTS")
    p.add_argument("--skip-email", action="store_true", help="Generate everything but don't send the email")
    p.add_argument("--no-sheets", action="store_true", help="Skip the Google Sheets step")
    p.add_argument("--no-slides", action="store_true", help="Skip the Google Slides step")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    cfg = Config.from_env()

    if args.channels is not None:
        cfg.channels = [c.strip() for c in args.channels.split(",") if c.strip()]
    if args.keywords is not None:
        cfg.keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]
    if args.lookback is not None:
        cfg.lookback_days = args.lookback
    if args.max_results is not None:
        cfg.max_results = args.max_results

    if not cfg.channels and not cfg.keywords:
        log("ERROR: no channels or keywords provided. Add to .env or pass --channels/--keywords.")
        return 2

    try:
        cfg.require_youtube_key()
    except RuntimeError as e:
        log(f"ERROR: {e}")
        return 2

    log("[pipeline] step 1/5 — fetch")
    try:
        videos = fetch_videos(
            api_key=cfg.youtube_api_key,
            channels=cfg.channels,
            keywords=cfg.keywords,
            lookback_days=cfg.lookback_days,
            max_results=cfg.max_results,
            log=log,
        )
    except HttpError as e:
        log(f"ERROR (YouTube API): {e}")
        if "quota" in str(e).lower():
            log("Hint: you may have exceeded the daily quota for the YouTube Data API.")
        return 3

    log("[pipeline] step 2/5 — analyze")
    report = analyze(videos, lookback_days=cfg.lookback_days)
    log(f"[analyze] {report.headline}")

    sheets_url: str | None = None
    if args.no_sheets:
        log("[pipeline] step 3/5 — sheets (skipped)")
    else:
        log("[pipeline] step 3/5 — write to Google Sheets")
        try:
            from src.sheets import write_report as write_sheet
            sheets_url = write_sheet(cfg, report, log=log)
            log(f"[sheets] {sheets_url}")
        except FileNotFoundError as e:
            log(f"ERROR: {e}")
            return 4
        except HttpError as e:
            log(f"ERROR (Sheets API): {e}")
            return 4

    slides_url: str = ""
    if args.no_slides:
        log("[pipeline] step 4/5 — slides (skipped)")
    else:
        log("[pipeline] step 4/5 — generate Google Slides deck")
        try:
            from src.slides import write_deck
            slides_url = write_deck(cfg, report, log=log)
            log(f"[slides] {slides_url}")
        except FileNotFoundError as e:
            log(f"ERROR: {e}")
            return 5
        except HttpError as e:
            log(f"ERROR (Slides API): {e}")
            return 5

    if args.skip_email or not slides_url:
        if args.skip_email:
            log("[pipeline] step 5/5 — email (skipped)")
        else:
            log("[pipeline] step 5/5 — email (skipped because no slide deck URL)")
    else:
        log("[pipeline] step 5/5 — send email via Gmail")
        try:
            from src.gmail import send_report
            send_report(cfg, report, slides_url=slides_url, sheets_url=sheets_url, log=log)
        except RuntimeError as e:
            log(f"ERROR: {e}")
            return 6
        except HttpError as e:
            log(f"ERROR (Gmail API): {e}")
            return 6

    log("[pipeline] DONE")
    if sheets_url:
        log(f"  sheet: {sheets_url}")
    if slides_url:
        log(f"  deck:  {slides_url}")
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
