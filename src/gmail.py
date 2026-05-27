"""Send the weekly report email via the Gmail API."""
from __future__ import annotations

import base64
from email.message import EmailMessage
from typing import Callable

from googleapiclient.discovery import build

from .analyze import Report
from .auth import get_credentials
from .config import Config


def _gmail_client():
    creds = get_credentials()
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _build_html(report: Report, *, slides_url: str, sheets_url: str | None) -> str:
    insights_html = "".join(f"<li>{i}</li>" for i in report.insights) or "<li>—</li>"
    top_rows = "".join(
        f"""<tr>
              <td style="padding:8px 12px;border-bottom:1px solid #eef0f3;">{v.title[:80]}</td>
              <td style="padding:8px 12px;border-bottom:1px solid #eef0f3;color:#5b6472;">{v.channel_title}</td>
              <td style="padding:8px 12px;border-bottom:1px solid #eef0f3;text-align:right;">{v.views:,}</td>
            </tr>"""
        for v in report.top_videos
    )

    sheet_button = (
        f'<a href="{sheets_url}" style="display:inline-block;padding:10px 18px;border-radius:8px;'
        f'background:#eef2ff;color:#4338ca;text-decoration:none;font-weight:600;font-size:14px;margin-left:8px;">'
        f"Open the data sheet</a>"
        if sheets_url else ""
    )

    return f"""<!doctype html>
<html><head><meta charset="utf-8"/></head>
<body style="margin:0;padding:0;background:#f3f4f6;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:#1f2937;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="padding:32px 16px;">
    <tr><td align="center">
      <table role="presentation" width="640" cellspacing="0" cellpadding="0" border="0" style="max-width:640px;background:#fff;border-radius:14px;overflow:hidden;box-shadow:0 1px 3px rgba(15,23,42,0.06);">
        <tr><td style="background:linear-gradient(135deg,#4f46e5,#3730a3);padding:24px 32px;color:#fff;">
          <div style="font-size:11px;letter-spacing:0.12em;text-transform:uppercase;opacity:0.85;">YouTube Analyst</div>
          <div style="font-size:22px;font-weight:700;margin-top:6px;">Weekly trend report</div>
          <div style="font-size:13px;opacity:0.85;margin-top:4px;">Generated {report.generated_at}</div>
        </td></tr>
        <tr><td style="padding:24px 32px 8px;font-size:15px;line-height:1.6;">
          {report.headline}
        </td></tr>
        <tr><td style="padding:8px 32px;">
          <a href="{slides_url}" style="display:inline-block;padding:10px 18px;border-radius:8px;background:#4f46e5;color:#fff;text-decoration:none;font-weight:600;font-size:14px;">Open the slide deck</a>
          {sheet_button}
        </td></tr>
        <tr><td style="padding:20px 32px 0;">
          <div style="font-size:11px;letter-spacing:0.12em;text-transform:uppercase;color:#6b7280;font-weight:600;">Insights</div>
          <ul style="margin:8px 0 0;padding-left:20px;">{insights_html}</ul>
        </td></tr>
        <tr><td style="padding:24px 32px;">
          <div style="font-size:11px;letter-spacing:0.12em;text-transform:uppercase;color:#6b7280;font-weight:600;margin-bottom:10px;">Top videos</div>
          <table cellspacing="0" cellpadding="0" border="0" style="width:100%;border-collapse:collapse;font-size:13px;">
            {top_rows}
          </table>
        </td></tr>
        <tr><td style="padding:0 32px 28px;color:#9ca3af;font-size:12px;border-top:1px solid #eef0f3;padding-top:16px;">
          Sent automatically by your YouTube Analyst pipeline.
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""


def _build_text(report: Report, slides_url: str, sheets_url: str | None) -> str:
    lines = [
        f"YouTube Analyst — Weekly Report ({report.generated_at})",
        "",
        report.headline,
        "",
        f"Slide deck: {slides_url}",
    ]
    if sheets_url:
        lines.append(f"Data sheet: {sheets_url}")
    lines.append("")
    lines.append("Insights:")
    lines += [f"  - {i}" for i in (report.insights or ["(none)"])]
    lines.append("")
    lines.append("Top videos:")
    for v in report.top_videos:
        lines.append(f"  - {v.title[:80]} — {v.channel_title} ({v.views:,} views)")
    return "\n".join(lines) + "\n"


def send_report(
    cfg: Config,
    report: Report,
    *,
    slides_url: str,
    sheets_url: str | None = None,
    log: Callable[[str], None] = print,
) -> str:
    cfg.require_email()
    svc = _gmail_client()

    message = EmailMessage()
    message["To"] = cfg.recipient_email
    message["From"] = cfg.sender_email
    message["Subject"] = "YouTube Analyst — Weekly Report"
    message.set_content(_build_text(report, slides_url, sheets_url))
    message.add_alternative(_build_html(report, slides_url=slides_url, sheets_url=sheets_url),
                            subtype="html")

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    sent = svc.users().messages().send(userId="me", body={"raw": raw}).execute()
    log(f"[gmail] sent to {cfg.recipient_email} (id={sent.get('id')})")
    return sent.get("id", "")
