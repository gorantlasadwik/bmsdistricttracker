"""
ShowPulser – Notification Dispatcher
Coordinates all enabled notifiers and handles deduplication.
"""
from __future__ import annotations

from loguru import logger

from app import database as db
from app.config import settings
from app.models import ChangeEvent
from app.notifier.base import BaseNotifier
from app.notifier.discord import DiscordNotifier
from app.notifier.email_notifier import EmailNotifier
from app.notifier.telegram import TelegramNotifier
from app.notifier.whatsapp import WhatsAppNotifier


_ALL_NOTIFIERS: dict[str, type[BaseNotifier]] = {
    "telegram": TelegramNotifier,
    "discord": DiscordNotifier,
    "whatsapp": WhatsAppNotifier,
    "email": EmailNotifier,
}


def _build_notifiers() -> list[BaseNotifier]:
    enabled = settings.notifiers_list()
    notifiers = []
    for name in enabled:
        cls = _ALL_NOTIFIERS.get(name)
        if cls:
            notifiers.append(cls())
            logger.debug(f"[Dispatcher] Loaded notifier: {name}")
        else:
            logger.warning(f"[Dispatcher] Unknown notifier '{name}' in ENABLED_NOTIFIERS")
    return notifiers


# Build once at import time
_notifiers: list[BaseNotifier] = _build_notifiers()


async def dispatch(
    movie_id: int,
    movie_name: str,
    changes: list[ChangeEvent],
    source_url: str = "",
) -> int:
    """
    Filter out already-notified changes, then send via all enabled notifiers.

    Returns:
        Number of new (un-deduplicated) changes dispatched.
    """
    if not changes:
        return 0

    # ── Deduplication ──────────────────────────────────────────────────────────
    new_changes: list[ChangeEvent] = []
    for change in changes:
        already_sent = await db.was_notified(movie_id, change.type, change.detail)
        if already_sent:
            logger.debug(f"[Dispatcher] Skipping duplicate: {change.type} – {change.detail}")
        else:
            new_changes.append(change)

    if not new_changes:
        logger.info(f"[Dispatcher] All {len(changes)} change(s) already notified. Nothing new to send.")
        return 0

    logger.info(
        f"[Dispatcher] Sending {len(new_changes)} new change(s) for '{movie_name}' "
        f"via {[n.name for n in _notifiers]}"
    )

    # ── Send via all enabled notifiers concurrently ────────────────────────────
    async def safe_send(notifier: BaseNotifier):
        try:
            success = await notifier.send(movie_name, new_changes, source_url)
            if success:
                logger.info(f"[{notifier.name.title()}] ✓ Sent")
            else:
                logger.warning(f"[{notifier.name.title()}] ✗ Failed")
        except Exception as e:
            logger.error(f"[{notifier.name.title()}] Unexpected error: {e}")

    # Sort notifiers to prioritize whatsapp and initiate it first
    sorted_notifiers = sorted(_notifiers, key=lambda n: 0 if n.name == "whatsapp" else 1)

    import asyncio
    await asyncio.gather(*(safe_send(notifier) for notifier in sorted_notifiers))

    # ── Record as sent ─────────────────────────────────────────────────────────
    for change in new_changes:
        await db.record_notification(movie_id, change.type, change.detail)

    return len(new_changes)
