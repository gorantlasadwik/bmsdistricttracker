"""
ShowPulser – WhatsApp Notifier (via Green API)

Free tier: 500 messages/month, no credit card needed.

Setup (one-time):
  1. Go to https://console.green-api.com/ and register
  2. Create a free "Developer" instance
  3. Scan the QR code with WhatsApp (Settings → Linked Devices)
  4. Copy Instance ID and API Token
  5. Set in .env:
       GREENAPI_INSTANCE_ID=1101234567
       GREENAPI_API_TOKEN=your_token_here
       GREENAPI_RECIPIENT=919876543210   (your WhatsApp number, digits only, no + or spaces)
"""
from __future__ import annotations

import httpx
from loguru import logger

from app.config import settings
from app.models import ChangeEvent, SourceSnapshot
from app.notifier.base import BaseNotifier


class WhatsAppNotifier(BaseNotifier):
    """Sends WhatsApp messages via Green API (free, QR code based)."""

    @property
    def name(self) -> str:
        return "whatsapp"

    async def send(
        self,
        movie_name: str,
        changes: list[ChangeEvent],
        source_url: str = "",
    ) -> bool:
        instance_id = getattr(settings, "greenapi_instance_id", "") or ""
        api_token   = getattr(settings, "greenapi_api_token",   "") or ""
        recipient   = getattr(settings, "greenapi_recipient",   "") or ""

        if not instance_id or not api_token or not recipient:
            logger.warning(
                "[WhatsApp] Green API credentials not set "
                "(GREENAPI_INSTANCE_ID / GREENAPI_API_TOKEN / GREENAPI_RECIPIENT). Skipping."
            )
            return False

        if not changes:
            return True

        # Conserve WhatsApp message limit by filtering high-priority changes only
        allowed_types = {"new_theatre", "new_show", "booking_open"}
        filtered_changes = [c for c in changes if c.type in allowed_types]

        if not filtered_changes:
            logger.info("[WhatsApp] Skipping WhatsApp message since changes don't include new theatres/shows/booking open.")
            return True

        body = self._build_message(movie_name, filtered_changes, source_url)

        # Green API endpoint
        base_url = (settings.greenapi_api_url or "https://api.green-api.com").rstrip("/")
        url = (
            f"{base_url}/waInstance{instance_id}"
            f"/sendMessage/{api_token}"
        )
        
        # Split multiple recipients (comma-separated)
        recipients = [r.strip() for r in recipient.split(",") if r.strip()]
        if not recipients:
            logger.warning("[WhatsApp] No recipients found in GREENAPI_RECIPIENT setting.")
            return False

        success_count = 0
        async with httpx.AsyncClient(timeout=20) as client:
            for r in recipients:
                # Clean up characters
                clean_r = r.lstrip("+").replace(" ", "").replace("-", "")
                if not clean_r.isdigit():
                    logger.warning(f"[WhatsApp] Invalid recipient number skipped: {r}")
                    continue
                
                # Prepend Indian country code if 10-digit number is provided
                if len(clean_r) == 10:
                    clean_r = f"91{clean_r}"

                chat_id = f"{clean_r}@c.us"
                payload = {
                    "chatId": chat_id,
                    "message": body,
                }

                try:
                    resp = await client.post(url, json=payload)
                    data = resp.json()
                    if resp.status_code == 200 and data.get("idMessage"):
                        logger.info(f"[WhatsApp] Message sent to {clean_r} (id={data['idMessage']})")
                        success_count += 1
                    else:
                        logger.error(f"[WhatsApp] Green API error for {clean_r}: {data}")
                except Exception as e:
                    logger.error(f"[WhatsApp] Failed to send to {clean_r}: {e}")

        return success_count > 0

    async def send_status_report(
        self,
        movie_name: str,
        snapshots: list[SourceSnapshot],
    ) -> bool:
        instance_id = getattr(settings, "greenapi_instance_id", "") or ""
        api_token   = getattr(settings, "greenapi_api_token",   "") or ""
        recipient   = getattr(settings, "greenapi_recipient",   "") or ""

        if not instance_id or not api_token or not recipient:
            logger.warning("[WhatsApp] Green API credentials not set. Skipping status report.")
            return False

        if not snapshots:
            return True

        body = self._build_status_message(movie_name, snapshots)

        # Green API endpoint
        base_url = (settings.greenapi_api_url or "https://api.green-api.com").rstrip("/")
        url = (
            f"{base_url}/waInstance{instance_id}"
            f"/sendMessage/{api_token}"
        )
        
        # Split multiple recipients (comma-separated)
        recipients = [r.strip() for r in recipient.split(",") if r.strip()]
        if not recipients:
            return False

        success_count = 0
        async with httpx.AsyncClient(timeout=20) as client:
            for r in recipients:
                # Clean up characters
                clean_r = r.lstrip("+").replace(" ", "").replace("-", "")
                if not clean_r.isdigit():
                    continue
                if len(clean_r) == 10:
                    clean_r = f"91{clean_r}"

                chat_id = f"{clean_r}@c.us"
                payload = {
                    "chatId": chat_id,
                    "message": body,
                }

                try:
                    resp = await client.post(url, json=payload)
                    data = resp.json()
                    if resp.status_code == 200 and data.get("idMessage"):
                        logger.info(f"[WhatsApp] Status report sent to {clean_r} (id={data['idMessage']})")
                        success_count += 1
                except Exception as e:
                    logger.error(f"[WhatsApp] Failed to send status report to {clean_r}: {e}")

        return success_count > 0

    def _build_status_message(
        self,
        movie_name: str,
        snapshots: list[SourceSnapshot],
    ) -> str:
        lines = [f"📊 *{movie_name}* — Current Status Report\n"]

        for snap in snapshots:
            lines.append(f"📍 *{self._format_source_label(snap.source, snap.url)}*")
            if not snap.theatres:
                lines.append("  ⚠️ No theatres currently listing shows.")
                lines.append("")
                continue

            for t in snap.theatres:
                lines.append(f"  🏛 {t.theatre}")
                status_lbl = "Booking Open" if t.booking_open else "Booking Not Open"
                lines.append(f"    🟢 {status_lbl}" if t.booking_open else f"    🔴 {status_lbl}")
                if t.shows:
                    lines.append(f"    🕐 Shows: {', '.join(t.shows)}")
                if t.formats:
                    lines.append(f"    🎞 Formats: {', '.join(t.formats)}")
                if t.booking_url:
                    lines.append(f"    🔗 {t.booking_url}")
                lines.append("")

        return "\n".join(lines)

    def _build_message(
        self,
        movie_name: str,
        changes: list[ChangeEvent],
        source_url: str,
    ) -> str:
        lines = [f"🎬 *{movie_name}* — Show Update\n"]

        grouped_by_source: dict[str, list[ChangeEvent]] = {}
        for c in changes:
            grouped_by_source.setdefault(c.source, []).append(c)

        for source, src_changes in grouped_by_source.items():
            booking_url = next(
                (c.booking_url for c in src_changes if c.booking_url),
                source_url
            )
            lines.append(f"📍 *{self._format_source_label(source, booking_url)}*")
            grouped = self._group_changes_by_theatre(src_changes)
            for theatre, t_changes in grouped.items():
                lines.append(f"  🏛 *{theatre}*")
                for c in t_changes:
                    if c.type == "new_show":
                        lines.append("    🚨 *NEW SHOW ADDED*")
                        if c.before:
                            lines.append(f"    • *Before:* {c.before}")
                        if c.after:
                            after_formatted = c.after
                            if c.new_items:
                                shows = [s.strip() for s in c.after.split(",")]
                                highlighted = [f"*{s}*" if s in c.new_items else s for s in shows]
                                after_formatted = ", ".join(highlighted)
                            lines.append(f"    • *After:* {after_formatted}")
                        else:
                            lines.append(f"    • {c.detail}")

                    elif c.type == "new_theatre":
                        lines.append("    🏛️ *NEW THEATRE ADDED*")
                        if c.before:
                            lines.append(f"    • *Before:* {c.before}")
                        if c.after:
                            after_formatted = c.after
                            if c.new_items:
                                shows = [s.strip() for s in c.after.split(",")]
                                highlighted = [f"*{s}*" if s in c.new_items else s for s in shows]
                                after_formatted = ", ".join(highlighted)
                            lines.append(f"    • *After:* {after_formatted}")
                        else:
                            lines.append(f"    • {c.detail}")

                    elif c.type == "booking_open":
                        lines.append("    🟢 *BOOKING OPEN!*")

                    else:
                        lines.append(f"    • {c.detail}")

                    if c.booking_url:
                        lines.append(f"    🔗 {c.booking_url}")
            lines.append("")

        if source_url:
            lines.append(f"🌐 {source_url}")

        return "\n".join(lines)
