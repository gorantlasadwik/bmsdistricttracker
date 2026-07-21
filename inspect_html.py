"""Extract venue name from header and showtimes from venue-card."""
import sys, json, re
sys.path.insert(0, ".")
from bs4 import BeautifulSoup

with open("debug_html/bms_english_3d.html", encoding="utf-8") as f:
    html = f.read()
soup = BeautifulSoup(html, "lxml")
for script in soup.find_all("script"):
    if script.string and "__INITIAL_STATE__" in (script.string or ""):
        m = re.search(r"window\.__INITIAL_STATE__\s*=\s*(\{.*)", script.string, re.DOTALL)
        if m:
            state = json.loads(m.group(1).rstrip().rstrip(";"))
            break

dynamic_data = state["showtimesByEvent"]["showDates"]["20260730"]["dynamic"]["data"]
gl = next(w for w in dynamic_data["showtimeWidgets"] if w.get("type") == "groupList")
venue_cards = gl["data"][0]["data"]

# Also get static venue data (has venueName)
static_venues = state["showtimesByEvent"]["showDates"]["20260730"]["primaryStatic"]["data"]["venues"]

for card in venue_cards:
    vc = card.get("additionalData", {}).get("venueCode", "")
    
    # Name from static venues
    static = static_venues.get(vc, {})
    name = static.get("venueName", "?")
    
    # Header
    header = card.get("header", {})
    print(f"\nVenue: {name!r} (code={vc})")
    print(f"  header keys: {list(header.keys()) if header else 'N/A'}")
    if header:
        print(f"  header: {json.dumps(header)[:200]!r}")
    
    # Showtimes
    showtimes = card.get("showtimes", [])
    print(f"  showtimes count: {len(showtimes)}")
    for j, st in enumerate(showtimes[:3]):
        print(f"  showtime[{j}]: {json.dumps(st)[:300]!r}")
    
    # infoList  
    infos = card.get("infoList", [])
    print(f"  infoList count: {len(infos)}")
    for info in infos[:2]:
        print(f"  info: {json.dumps(info)[:200]!r}")
