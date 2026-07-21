"""
ShowPulser – Telegram Notifier
Uses python-telegram-bot v20+ async Bot.send_message().
"""
from __future__ import annotations

from loguru import logger
from telegram import Bot
from telegram.constants import ParseMode

from app.config import settings
from app.models import ChangeEvent, ChangeType
from app.notifier.base import BaseNotifier


_ICON_MAP = {
    ChangeType.NEW_THEATRE: "🏛",
    ChangeType.NEW_SHOW: "🕐",
    ChangeType.NEW_FORMAT: "🎞",
    ChangeType.BOOKING_OPEN: "🟢",
    ChangeType.SHOW_REMOVED: "❌",
    ChangeType.FORMAT_REMOVED: "❌",
    "theatre_removed": "🏚",
}

_SOURCE_ICON = {
    "bookmyshow": "🎟",
    "district": "🎫",
}


class TelegramNotifier(BaseNotifier):
    """Sends rich Markdown notifications via Telegram Bot API."""

    @property
    def name(self) -> str:
        return "telegram"

    async def send(
        self,
        movie_name: str,
        changes: list[ChangeEvent],
        source_url: str = "",
    ) -> bool:
        if not settings.telegram_bot_token or not settings.telegram_chat_id:
            logger.warning("[Telegram] Token or Chat ID not configured. Skipping.")
            return False

        if not changes:
            return True

        message = self._build_message(movie_name, changes, source_url)

        try:
            bot = Bot(token=settings.telegram_bot_token)
            await bot.send_message(
                chat_id=settings.telegram_chat_id,
                text=message,
                parse_mode=ParseMode.MARKDOWN_V2,
                disable_web_page_preview=False,
            )
            logger.info(f"[Telegram] Notification sent for '{movie_name}' ({len(changes)} changes)")
            return True
        except Exception as e:
            logger.error(f"[Telegram] Failed to send notification: {e}")
            return False

    def _build_message(
        self,
        movie_name: str,
        changes: list[ChangeEvent],
        source_url: str,
    ) -> str:
        lines: list[str] = []

        # ── Header ───────────────────────────────────────────────────────────
        safe_name = _escape(movie_name)
        lines.append(f"🎬 *{safe_name} — Show Update*")
        lines.append("")

        # Group by source then by theatre
        sources: dict[str, list[ChangeEvent]] = {}
        for c in changes:
            sources.setdefault(c.source, []).append(c)

        for source, src_changes in sources.items():
            src_icon = _SOURCE_ICON.get(source, "📽")
            booking_url = next(
                (c.booking_url for c in src_changes if c.booking_url),
                source_url
            )
            src_label = _escape(self._format_source_label(source, booking_url))
            lines.append(f"{src_icon} *{src_label}*")
            lines.append("")

            grouped = self._group_changes_by_theatre(src_changes)
            for theatre, t_changes in grouped.items():
                lines.append(f"  🏛 *{_escape(theatre)}*")

                for c in t_changes:
                    if c.type == "new_show":
                        lines.append("    🚨 *NEW SHOW ADDED*")
                        if c.before:
                            lines.append(f"    • *Before:* {_escape(c.before)}")
                        if c.after:
                            after_formatted = _escape(c.after)
                            if c.new_items:
                                shows = [s.strip() for s in c.after.split(",")]
                                highlighted = [f"__*{_escape(s)}*__" if s in c.new_items else _escape(s) for s in shows]
                                after_formatted = ", ".join(highlighted)
                            lines.append(f"    • *After:* {after_formatted}")
                        else:
                            lines.append(f"    • {_escape(c.detail)}")

                    elif c.type == "new_theatre":
                        lines.append("    🏛️ *NEW THEATRE ADDED*")
                        if c.before:
                            lines.append(f"    • *Before:* {_escape(c.before)}")
                        if c.after:
                            after_formatted = _escape(c.after)
                            if c.new_items:
                                shows = [s.strip() for s in c.after.split(",")]
                                highlighted = [f"__*{_escape(s)}*__" if s in c.new_items else _escape(s) for s in shows]
                                after_formatted = ", ".join(highlighted)
                            lines.append(f"    • *After:* {after_formatted}")
                        else:
                            lines.append(f"    • {_escape(c.detail)}")

                    elif c.type == "booking_open":
                        lines.append("    🟢 *BOOKING OPEN!*")

                    else:
                        icon = _ICON_MAP.get(c.type, "📌")
                        detail = _escape(c.detail)
                        lines.append(f"    {icon} {detail}")

                # Add booking link if available
                booking_url = next(
                    (c.booking_url for c in t_changes if c.booking_url),
                    None,
                )
                if booking_url:
                    lines.append(f"    🔗 [Book Tickets]({_escape_url(booking_url)})")

                lines.append("")

        # ── Source URL ────────────────────────────────────────────────────────
        if source_url:
            lines.append(f"🌐 [View on site]({_escape_url(source_url)})")

        return "\n".join(lines)

    async def send_status_report(
        self,
        movie_name: str,
        snapshots: list[SourceSnapshot],
    ) -> bool:
        if not settings.telegram_bot_token or not settings.telegram_chat_id:
            logger.warning("[Telegram] Token or Chat ID not configured. Skipping.")
            return False

        if not snapshots:
            return True

        message = self._build_status_message(movie_name, snapshots)

        try:
            bot = Bot(token=settings.telegram_bot_token)
            await bot.send_message(
                chat_id=settings.telegram_chat_id,
                text=message,
                parse_mode=ParseMode.MARKDOWN_V2,
                disable_web_page_preview=False,
            )
            logger.info(f"[Telegram] Status report sent for '{movie_name}'")
            return True
        except Exception as e:
            logger.error(f"[Telegram] Failed to send status report: {e}")
            return False

    def _build_status_message(
        self,
        movie_name: str,
        snapshots: list[SourceSnapshot],
    ) -> str:
        lines: list[str] = []
        safe_name = _escape(movie_name)
        lines.append(f"📊 *{safe_name} — Current Status Report*")
        lines.append("")

        for snap in snapshots:
            src_icon = _SOURCE_ICON.get(snap.source, "📽")
            src_label = _escape(self._format_source_label(snap.source))
            lines.append(f"{src_icon} *{src_label}*")
            if snap.url:
                lines.append(f"🌐 [View Link]({_escape_url(snap.url)})")
            lines.append("")

            if not snap.theatres:
                lines.append("  ⚠️ _No theatres currently listing shows._")
                lines.append("")
                continue

            for t in snap.theatres:
                lines.append(f"  🏛 *{_escape(t.theatre)}*")
                status_icon = "🟢" if t.booking_open else "🔴"
                status_lbl = "Booking Open" if t.booking_open else "Booking Not Open"
                lines.append(f"    {status_icon} {status_lbl}")
                if t.shows:
                    lines.append(f"    🕐 Shows: {_escape(', '.join(t.shows))}")
                if t.formats:
                    lines.append(f"    🎞 Formats: {_escape(', '.join(t.formats))}")
                if t.booking_url:
                    lines.append(f"    🔗 [Book Tickets]({_escape_url(t.booking_url)})")
                lines.append("")

        return "\n".join(lines)



def _escape(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    special = r"\_*[]()~`>#+-=|{}.!"
    return "".join(f"\\{c}" if c in special else c for c in str(text))


def _escape_url(url: str) -> str:
    """Escape parentheses in URLs for MarkdownV2 links."""
    return url.replace("(", "%28").replace(")", "%29")
