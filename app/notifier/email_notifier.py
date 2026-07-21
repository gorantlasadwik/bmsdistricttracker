"""
ShowPulser – Email Notifier (async SMTP via aiosmtplib)
"""
from __future__ import annotations

import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib
from loguru import logger

from app.config import settings
from app.models import ChangeEvent
from app.notifier.base import BaseNotifier


class EmailNotifier(BaseNotifier):
    """Sends HTML email notifications via SMTP."""

    @property
    def name(self) -> str:
        return "email"

    async def send(
        self,
        movie_name: str,
        changes: list[ChangeEvent],
        source_url: str = "",
    ) -> bool:
        if not all([settings.smtp_user, settings.smtp_password, settings.smtp_to]):
            logger.warning("[Email] SMTP credentials not configured. Skipping.")
            return False

        if not changes:
            return True

        subject = f"🎬 {movie_name} — Show Update ({len(changes)} changes)"
        html_body = self._build_html(movie_name, changes, source_url)
        text_body = self._build_text(movie_name, changes, source_url)

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.smtp_user
        msg["To"] = settings.smtp_to
        msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        try:
            await aiosmtplib.send(
                msg,
                hostname=settings.smtp_host,
                port=settings.smtp_port,
                username=settings.smtp_user,
                password=settings.smtp_password,
                start_tls=True,
            )
            logger.info(f"[Email] Notification sent for '{movie_name}' to {settings.smtp_to}")
            return True
        except Exception as e:
            logger.error(f"[Email] Failed to send notification: {e}")
            return False

    def _build_text(self, movie_name: str, changes: list[ChangeEvent], source_url: str) -> str:
        lines = [f"Movie Update: {movie_name}\n"]
        for c in changes:
            src = self._format_source_label(c.source)
            lines.append(f"[{src}] {c.theatre}: {c.detail}")
            if c.booking_url:
                lines.append(f"  Book: {c.booking_url}")
        if source_url:
            lines.append(f"\nView: {source_url}")
        return "\n".join(lines)

    def _build_html(self, movie_name: str, changes: list[ChangeEvent], source_url: str) -> str:
        rows = ""
        grouped_by_source: dict[str, list[ChangeEvent]] = {}
        for c in changes:
            grouped_by_source.setdefault(c.source, []).append(c)

        for source, src_changes in grouped_by_source.items():
            src_label = self._format_source_label(source)
            rows += f"<tr><td colspan='3' style='background:#1e293b;color:#94a3b8;padding:8px 12px;font-size:12px;letter-spacing:1px;text-transform:uppercase'>{src_label}</td></tr>"

            grouped = self._group_changes_by_theatre(src_changes)
            for theatre, t_changes in grouped.items():
                rows += f"<tr><td colspan='3' style='padding:8px 12px;font-weight:bold;color:#e2e8f0;background:#0f172a'>{theatre}</td></tr>"
                for c in t_changes:
                    badge_colour = _badge_colour(c.type)
                    label = c.type.replace("_", " ").title()
                    rows += f"""
                    <tr>
                        <td style='padding:6px 12px;color:#cbd5e1'>{label}</td>
                        <td style='padding:6px 12px;color:#e2e8f0'>{c.detail}</td>
                        <td style='padding:6px 12px'>
                            {'<a href="' + c.booking_url + '" style="color:#818cf8">Book</a>' if c.booking_url else ''}
                        </td>
                    </tr>"""

        view_link = f'<a href="{source_url}" style="color:#818cf8">View on site →</a>' if source_url else ""

        return f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>{movie_name} Show Update</title></head>
<body style="background:#0f172a;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;margin:0;padding:20px">
  <div style="max-width:600px;margin:0 auto;background:#1e293b;border-radius:12px;overflow:hidden">
    <div style="background:linear-gradient(135deg,#6366f1,#8b5cf6);padding:24px">
      <h1 style="color:#fff;margin:0;font-size:20px">🎬 {movie_name}</h1>
      <p style="color:#c4b5fd;margin:4px 0 0">Show Update — {len(changes)} change(s) detected</p>
    </div>
    <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse">
      {rows}
    </table>
    <div style="padding:16px 12px;text-align:center">
      {view_link}
    </div>
  </div>
</body>
</html>"""


def _badge_colour(change_type: str) -> str:
    return {
        "new_theatre": "#6366f1",
        "new_show": "#22c55e",
        "new_format": "#f59e0b",
        "booking_open": "#22c55e",
        "show_removed": "#ef4444",
    }.get(change_type, "#64748b")
