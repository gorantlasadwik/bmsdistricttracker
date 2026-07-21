"""
ShowPulser – Tests: Notification Formatting
Tests message formatting without actually sending any notifications.
"""
import pytest

from app.models import ChangeEvent, ChangeType
from app.notifier.telegram import TelegramNotifier, _escape
from app.notifier.discord import DiscordNotifier, _pick_colour
from app.notifier.whatsapp import WhatsAppNotifier


def make_change(
    type_=ChangeType.NEW_THEATRE,
    theatre="PVR Palazzo",
    detail="New theatre added",
    source="bookmyshow",
    booking_url=None,
) -> ChangeEvent:
    return ChangeEvent(
        type=type_,
        source=source,
        theatre=theatre,
        detail=detail,
        booking_url=booking_url,
    )


# ── Telegram formatter ─────────────────────────────────────────────────────────

class TestTelegramFormatter:
    def setup_method(self):
        self.notifier = TelegramNotifier()

    def test_message_contains_movie_name(self):
        changes = [make_change()]
        msg = self.notifier._build_message("Spider-Man", changes, "https://bms.com")
        assert "Spider" in msg

    def test_message_contains_theatre_name(self):
        changes = [make_change(theatre="AGS Villivakkam")]
        msg = self.notifier._build_message("Test Movie", changes, "")
        assert "AGS" in msg

    def test_message_contains_source_label(self):
        changes = [make_change(source="bookmyshow")]
        msg = self.notifier._build_message("Test Movie", changes, "")
        assert "BookMyShow" in msg

    def test_booking_open_icon(self):
        changes = [make_change(type_=ChangeType.BOOKING_OPEN, detail="Booking is now OPEN!")]
        msg = self.notifier._build_message("Test Movie", changes, "")
        assert "🟢" in msg

    def test_booking_url_included(self):
        changes = [make_change(booking_url="https://in.bookmyshow.com/book/123")]
        msg = self.notifier._build_message("Test Movie", changes, "")
        assert "Book Tickets" in msg or "bookmyshow" in msg

    def test_multiple_sources_grouped(self):
        changes = [
            make_change(source="bookmyshow", theatre="PVR"),
            make_change(source="district", theatre="SPI Cinemas"),
        ]
        msg = self.notifier._build_message("Test Movie", changes, "")
        assert "BookMyShow" in msg
        assert "District" in msg

    def test_escape_special_chars(self):
        assert _escape("Hello.World!") == r"Hello\.World\!"
        assert _escape("(test)") == r"\(test\)"
        # Dash is a special char in MarkdownV2 and must be escaped
        assert _escape("no-special") == r"no\-special"
        assert _escape("plain text") == "plain text"

    def test_empty_changes_still_builds(self):
        msg = self.notifier._build_message("Test Movie", [], "")
        assert isinstance(msg, str)


# ── Discord formatter ──────────────────────────────────────────────────────────

class TestDiscordFormatter:
    def setup_method(self):
        self.notifier = DiscordNotifier()

    def test_fields_built_correctly(self):
        changes = [
            make_change(theatre="PVR", detail="09:00 added"),
            make_change(theatre="PVR", type_=ChangeType.BOOKING_OPEN, detail="Booking OPEN!"),
        ]
        fields = self.notifier._build_fields(changes)
        assert len(fields) >= 1
        assert any("PVR" in f["name"] for f in fields)

    def test_colour_booking_open(self):
        changes = [make_change(type_=ChangeType.BOOKING_OPEN)]
        colour = _pick_colour(changes)
        assert colour == 0x57F287  # Green

    def test_colour_new_theatre(self):
        changes = [make_change(type_=ChangeType.NEW_THEATRE)]
        colour = _pick_colour(changes)
        assert colour == 0x5865F2  # Blurple

    def test_colour_priority_booking_over_show(self):
        changes = [
            make_change(type_=ChangeType.NEW_SHOW),
            make_change(type_=ChangeType.BOOKING_OPEN),
        ]
        colour = _pick_colour(changes)
        assert colour == 0x57F287  # Booking open wins


# ── WhatsApp formatter ─────────────────────────────────────────────────────────

class TestWhatsAppFormatter:
    def setup_method(self):
        self.notifier = WhatsAppNotifier()

    def test_message_plain_text(self):
        changes = [make_change(theatre="Sathyam Cinemas", detail="09:00 added")]
        msg = self.notifier._build_message("Test Movie", changes, "https://example.com")
        assert "Sathyam Cinemas" in msg
        assert "09:00 added" in msg

    def test_url_included(self):
        changes = [make_change()]
        msg = self.notifier._build_message("Test Movie", changes, "https://bms.com/test")
        assert "https://bms.com/test" in msg
