"""
ShowPulser – Discord Notifier
Posts rich embed messages to a Discord webhook.
"""
from __future__ import annotations

import httpx
from loguru import logger

from app.config import settings
from app.models import ChangeEvent, ChangeType
from app.notifier.base import BaseNotifier


# Embed colours per change type
_COLOURS = {
    ChangeType.NEW_THEATRE: 0x5865F2,   # Discord Blurple
    ChangeType.NEW_SHOW: 0x57F287,       # Green
    ChangeType.NEW_FORMAT: 0xFEE75C,     # Yellow
    ChangeType.BOOKING_OPEN: 0x57F287,   # Green
    ChangeType.SHOW_REMOVED: 0xED4245,   # Red
}


class DiscordNotifier(BaseNotifier):
    """Sends embed notifications to a Discord webhook."""

    @property
    def name(self) -> str:
        return "discord"

    async def send(
        self,
        movie_name: str,
        changes: list[ChangeEvent],
        source_url: str = "",
    ) -> bool:
        if not settings.discord_webhook_url:
            logger.warning("[Discord] Webhook URL not configured. Skipping.")
            return False

        if not changes:
            return True

        # Determine embed colour by most "important" change type
        colour = _pick_colour(changes)
        fields = self._build_fields(changes)

        payload = {
            "username": "ShowPulser 🎬",
            "embeds": [
                {
                    "title": f"🎬 {movie_name} — Show Update",
                    "color": colour,
                    "fields": fields,
                    "footer": {"text": "ShowPulser • Live Show Monitor"},
                    "url": source_url or "",
                }
            ],
        }

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(settings.discord_webhook_url, json=payload)
                resp.raise_for_status()
            logger.info(f"[Discord] Notification sent for '{movie_name}'")
            return True
        except Exception as e:
            logger.error(f"[Discord] Failed to send notification: {e}")
            return False

    def _build_fields(self, changes: list[ChangeEvent]) -> list[dict]:
        fields: list[dict] = []
        grouped = self._group_changes_by_theatre(changes)

        for theatre, t_changes in grouped.items():
            lines = []
            for c in t_changes:
                label = c.type.replace("_", " ").title()
                lines.append(f"• **{label}**: {c.detail}")
                if c.booking_url:
                    lines.append(f"  → [Book]({c.booking_url})")

            source_label = self._format_source_label(t_changes[0].source)
            fields.append({
                "name": f"🏛 {theatre} ({source_label})",
                "value": "\n".join(lines) or "—",
                "inline": False,
            })

            if len(fields) >= 25:  # Discord embed field limit
                break

        return fields


def _pick_colour(changes: list[ChangeEvent]) -> int:
    priority = [
        ChangeType.BOOKING_OPEN,
        ChangeType.NEW_THEATRE,
        ChangeType.NEW_FORMAT,
        ChangeType.NEW_SHOW,
    ]
    types = {c.type for c in changes}
    for p in priority:
        if p in types:
            return _COLOURS.get(p, 0x5865F2)
    return 0x5865F2
