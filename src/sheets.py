"""Write the analyzed report to Google Sheets.

On first run (no SPREADSHEET_ID), creates a fresh spreadsheet and writes its ID back to .env.
On subsequent runs, appends a new tab named for today's date.
"""
from __future__ import annotations

from datetime import datetime
from typing import Callable

from googleapiclient.discovery import build

from .analyze import Report
from .auth import get_credentials
from .config import Config, write_env_value


SHEET_TITLE_PREFIX = "YouTube Trends — "

SUMMARY_HEADERS = ["Metric", "Value"]
VIDEO_HEADERS = [
    "Rank", "Title", "Channel", "Source Type", "Source Value",
    "Views", "Likes", "Comments", "Engagement %",
    "Published At", "Duration", "URL",
]


def _engagement_pct(v) -> float:
    if v.views <= 0:
        return 0.0
    return (v.likes + v.comments) / v.views * 100.0


def _sheets_client():
    creds = get_credentials()
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def _ensure_spreadsheet(svc, cfg: Config, log: Callable[[str], None]) -> str:
    if cfg.spreadsheet_id:
        return cfg.spreadsheet_id

    log("[sheets] no SPREADSHEET_ID — creating a new spreadsheet")
    spreadsheet = svc.spreadsheets().create(
        body={
            "properties": {"title": "YouTube Analyst — Weekly Reports"},
            "sheets": [{"properties": {"title": "_index"}}],
        }
    ).execute()
    sid = spreadsheet["spreadsheetId"]
    log(f"[sheets] created spreadsheet {sid}")
    write_env_value("SPREADSHEET_ID", sid)
    log("[sheets] saved SPREADSHEET_ID to .env")
    cfg.spreadsheet_id = sid
    return sid


def _add_tab(svc, spreadsheet_id: str, title: str) -> int:
    resp = svc.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": [{"addSheet": {"properties": {"title": title}}}]},
    ).execute()
    return resp["replies"][0]["addSheet"]["properties"]["sheetId"]


def _format_header_row(svc, spreadsheet_id: str, sheet_id: int) -> None:
    svc.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={
            "requests": [
                {
                    "repeatCell": {
                        "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1},
                        "cell": {
                            "userEnteredFormat": {
                                "textFormat": {"bold": True},
                                "backgroundColor": {"red": 0.95, "green": 0.95, "blue": 1.0},
                            }
                        },
                        "fields": "userEnteredFormat(textFormat,backgroundColor)",
                    }
                },
                {"updateSheetProperties": {
                    "properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1}},
                    "fields": "gridProperties.frozenRowCount",
                }},
            ]
        },
    ).execute()


def write_report(cfg: Config, report: Report, log: Callable[[str], None] = print) -> str:
    svc = _sheets_client()
    spreadsheet_id = _ensure_spreadsheet(svc, cfg, log)

    tab_title = datetime.utcnow().strftime("%Y-%m-%d %H%M UTC")
    log(f"[sheets] adding tab \"{tab_title}\"")
    sheet_id = _add_tab(svc, spreadsheet_id, tab_title)

    summary_rows = [
        SUMMARY_HEADERS,
        ["Generated at (UTC)", report.generated_at],
        ["Lookback (days)", report.lookback_days],
        ["Total videos", report.total_videos],
        ["Total views", report.total_views],
        ["Median views", report.median_views],
        ["Avg engagement %", f"{report.avg_engagement * 100:.2f}"],
        ["Avg duration", report.avg_duration_label],
        ["Headline", report.headline],
        [""],
        ["Insights"],
        *([i] for i in report.insights),
        [""],
        ["Top videos"],
    ]

    video_rows = [VIDEO_HEADERS]
    for i, v in enumerate(report.top_videos + report.standout_videos, start=1):
        video_rows.append([
            i,
            v.title,
            v.channel_title,
            v.source_type,
            v.source_value,
            v.views,
            v.likes,
            v.comments,
            round(_engagement_pct(v), 2),
            v.published_at,
            v.duration,
            v.url,
        ])

    all_rows = summary_rows + video_rows
    svc.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"'{tab_title}'!A1",
        valueInputOption="RAW",
        body={"values": all_rows},
    ).execute()

    _format_header_row(svc, spreadsheet_id, sheet_id)
    log(f"[sheets] wrote {len(all_rows)} rows to \"{tab_title}\"")
    return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit#gid={sheet_id}"
