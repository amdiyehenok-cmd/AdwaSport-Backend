#!/usr/bin/env python3
"""
AdwaSport Godly Match Fetcher
- Fetches upcoming fixtures AND live scores from TheSportsDB
- Merges real‑time match status (1H, 2H, HT, Live, etc.)
- Corrects league names using a canonical mapping
- Deduplicates matches across all leagues
- Outputs clean matches.json
"""

import requests
import json
from datetime import datetime, timedelta, timezone

# ========== CONFIGURATION ==========
LEAGUES = [
    {"id": "4328", "name": "English Premier League"},
    {"id": "4330", "name": "La Liga"},
    {"id": "4332", "name": "Serie A"},
    {"id": "4331", "name": "Bundesliga"},
    {"id": "4334", "name": "Ligue 1"},
    {"id": "4480", "name": "UEFA Champions League"},
    {"id": "4481", "name": "UEFA Europa League"},
    {"id": "4959", "name": "Ethiopian Premier League"},
]

OUTPUT_FILE = "matches.json"
API_KEY = "3"
DAYS_AHEAD = 7

# League name corrections (from API's strLeague to our canonical name)
LEAGUE_NAME_MAP = {
    "English League 1": "English League One",
    "English League 2": "English League Two",
    "English Premier League": "English Premier League",
    "La Liga": "La Liga",
    "Serie A": "Serie A",
    "Bundesliga": "Bundesliga",
    "Ligue 1": "Ligue 1",
    "UEFA Champions League": "UEFA Champions League",
    "UEFA Europa League": "UEFA Europa League",
    "Ethiopian Premier League": "Ethiopian Premier League",
}

def fetch_live_events(league_id):
    """Fetch currently live events for a league, capturing in‑play statuses."""
    url = f"https://www.thesportsdb.com/api/v1/json/{API_KEY}/livescore.php"
    try:
        resp = requests.get(url, params={"l": league_id}, timeout=15)
        resp.raise_for_status()
        live_events = resp.json().get("events") or []
        # Standardise and capture more "live" statuses
        for ev in live_events:
            status = ev.get("strStatus", "").lower()
            if status in ["1h", "2h", "ht", "live", "in progress"]:
                ev["strStatus"] = status  # keep the original status (e.g., "1H")
            else:
                ev["strStatus"] = "Live"  # fallback
        return live_events
    except:
        return []

def fetch_upcoming_events(league_id):
    """Fetch next 15 events for a league."""
    url = f"https://www.thesportsdb.com/api/v1/json/{API_KEY}/eventsnextleague.php"
    try:
        resp = requests.get(url, params={"id": league_id}, timeout=15)
        resp.raise_for_status()
        return resp.json().get("events") or []
    except:
        return []

def filter_upcoming(events):
    """Keep only events happening within the next DAYS_AHEAD days."""
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=DAYS_AHEAD)
    upcoming = []
    for ev in events:
        if not ev:
            continue
        ts = ev.get("strTimestamp") or ev.get("dateEvent")
        if not ts:
            continue
        try:
            if "T" in ts:
                dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S")
            else:
                dt = datetime.strptime(ts, "%Y-%m-%d")
            dt = dt.replace(tzinfo=timezone.utc)
            if now <= dt <= cutoff:
                upcoming.append(ev)
        except:
            pass
    return upcoming

def correct_league_name(raw_name):
    return LEAGUE_NAME_MAP.get(raw_name, raw_name)

def main():
    all_matches = {}
    live_status_map = {}

    print("📡 Fetching LIVE scores for all leagues...")
    for league in LEAGUES:
        live_events = fetch_live_events(league["id"])
        for ev in live_events:
            ev_id = ev.get("idEvent")
            if ev_id:
                live_status_map[ev_id] = ev.get("strStatus", "Live")
        print(f"   {league['name']}: {len(live_events)} live")

    print("\n📡 Fetching upcoming fixtures...")
    for league in LEAGUES:
        print(f"   {league['name']}...", end=" ")
        events = fetch_upcoming_events(league["id"])
        upcoming = filter_upcoming(events)
        for ev in upcoming:
            ev_id = ev["idEvent"]
            # Apply live status if available
            if ev_id in live_status_map:
                ev["strStatus"] = live_status_map[ev_id]
            elif not ev.get("strStatus"):
                ev["strStatus"] = "Not Started"
            # Correct league name
            raw_league = ev.get("strLeague", "")
            ev["strLeague"] = correct_league_name(raw_league)
            ev["fetched_for_league"] = league["name"]
            # Store, deduplicating by idEvent
            if ev_id not in all_matches:
                all_matches[ev_id] = ev
        print(f"✅ {len(upcoming)} matches")

    matches_list = list(all_matches.values())
    matches_list.sort(key=lambda x: x.get("strTimestamp", ""))

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(matches_list, f, indent=2, ensure_ascii=False)

    live_count = sum(1 for m in matches_list if m.get("strStatus") not in ("Not Started", None))
    print(f"\n🎯 Saved {len(matches_list)} unique matches ({live_count} live/in‑play)")

if __name__ == "__main__":
    main()