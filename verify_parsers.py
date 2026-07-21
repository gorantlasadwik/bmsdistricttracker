"""Verify parsers against saved HTML (no browser needed)."""
import re
from bs4 import BeautifulSoup

with open("debug_html/bms_english_3d.html", encoding="utf-8") as f:
    bms_html = f.read()
with open("debug_html/district.html", encoding="utf-8") as f:
    dist_html = f.read()

# Patch sys.path
import sys; sys.path.insert(0, ".")
from app.parsers.bms import BookMyShowParser, _TIME_RE
from app.parsers.district import DistrictParser

bms_parser = BookMyShowParser()
dist_parser = DistrictParser()

print("=" * 60)
print("BMS STATE JSON test (from saved HTML)")
print("=" * 60)
snap = bms_parser._parse_state_json(bms_html, "https://in.bookmyshow.com/movies/chennai/spider-man-brand-new-day/buytickets/ET00502600/20260730", "Spider-Man")

print(f"Theatres: {len(snap.theatres)}")
for t in snap.theatres:
    print(f"  {t.theatre}")
    print(f"    Shows: {t.shows}")
    print(f"    Formats: {t.formats}")
    print(f"    Booking: {t.booking_open}")

print()
print("=" * 60)
print("DISTRICT DOM test (from saved HTML)")
print("=" * 60)
snap2 = dist_parser._parse_dom(dist_html, "https://www.district.in/...?frmtid=rrfdpndypd", "Spider-Man")
print(f"Theatres: {len(snap2.theatres)}")
for t in snap2.theatres:
    print(f"  {t.theatre}")
    print(f"    Shows: {t.shows}")
    print(f"    Formats: {t.formats}")
    print(f"    Booking: {t.booking_open}")
