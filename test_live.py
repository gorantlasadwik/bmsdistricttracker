"""
Live integration test – runs the actual parsers against real URLs.
Run: python test_live.py

This does NOT require the full FastAPI server to be running.
It directly invokes the parsers and prints the result.
"""
import asyncio
import sys
from pathlib import Path

# Allow running from project root
sys.path.insert(0, str(Path(__file__).parent))

from app.browser import browser_pool
from app.parsers.bms import BookMyShowParser
from app.parsers.district import DistrictParser


BMS_URLS = [
    "https://in.bookmyshow.com/movies/chennai/spider-man-brand-new-day/buytickets/ET00502600/20260730",
    "https://in.bookmyshow.com/movies/chennai/spider-man-brand-new-day-epiq-3d/buytickets/ET00505581/20260801",
]

DISTRICT_URL = (
    "https://www.district.in/movies/spider-man-brand-new-day-movie-tickets-in-"
    "chennai-MV194537?frmtid=rrfdpndypd&fromdate=2026-08-01"
)

MOVIE_NAME = "Spider-Man: Brand New Day"


def print_snapshot(snapshot) -> None:
    print(f"\n{'='*60}")
    print(f"Source  : {snapshot.source.upper()}")
    print(f"Movie   : {snapshot.movie_name}")
    print(f"URL     : {snapshot.url[:80]}...")
    print(f"Fetched : {snapshot.timestamp}")
    print(f"Theatres: {len(snapshot.theatres)}")
    print("-" * 60)

    if not snapshot.theatres:
        print("  ⚠  No theatres found in snapshot")
        return

    for t in snapshot.theatres:
        booking_icon = "🟢" if t.booking_open else "🔴"
        print(f"\n  {booking_icon} {t.theatre}")
        if t.shows:
            print(f"     Shows   : {', '.join(t.shows)}")
        else:
            print(f"     Shows   : (none)")
        if t.formats:
            print(f"     Formats : {', '.join(t.formats)}")
        if t.booking_url:
            print(f"     Book    : {t.booking_url[:60]}...")


async def main():
    print("ShowPulser – Live Parser Test")
    print("=" * 60)

    await browser_pool.start()

    bms_parser = BookMyShowParser()
    district_parser = DistrictParser()

    try:
        # Test BMS URLs
        for url in BMS_URLS:
            print(f"\n[BMS] Testing: {url[:80]}...")
            try:
                snapshot = await bms_parser.fetch(url, MOVIE_NAME)
                print_snapshot(snapshot)
            except Exception as e:
                print(f"  ✗ Error: {e}")

        # Test District URL
        print(f"\n[District] Testing: {DISTRICT_URL[:80]}...")
        try:
            snapshot = await district_parser.fetch(DISTRICT_URL, MOVIE_NAME)
            print_snapshot(snapshot)
        except Exception as e:
            print(f"  ✗ Error: {e}")

    finally:
        await browser_pool.stop()

    print("\n" + "=" * 60)
    print("Live test complete.")


if __name__ == "__main__":
    asyncio.run(main())
