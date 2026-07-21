"""
Quick WhatsApp live test using Green API.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.notifier.whatsapp import WhatsAppNotifier
from app.models import ChangeEvent

async def run():
    # Force UTF-8 output on Windows terminals
    if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

    notifier = WhatsAppNotifier()
    
    # Create a dummy change event
    event = ChangeEvent(
        source="bookmyshow",
        type="booking_open",
        theatre="Test Theatre",
        detail="Theatre Added: Test Cinemas (OMR)",
        booking_url="https://in.bookmyshow.com/movies/chennai/spider-man-brand-new-day/buytickets/ET00502600/20260730"
    )
    
    print("Sending live test WhatsApp message via Green API...")
    success = await notifier.send(
        movie_name="Spider-Man: Brand New Day",
        changes=[event],
        source_url="https://in.bookmyshow.com"
    )
    
    if success:
        print("[SUCCESS] Test message sent successfully!")
    else:
        print("[FAIL] Failed to send test message. Check application log or Green API credentials.")

if __name__ == "__main__":
    asyncio.run(run())
