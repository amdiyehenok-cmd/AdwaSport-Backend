#!/usr/bin/env python3
"""
Fetch upcoming sports events from TheSportsDB (free API).
Outputs matches.json with events for the next 7 days.
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
    {"id": "4387", "name": "NBA"},
    {"id": "4391", "name": "NFL"},
    {"id": "4424", "name": "MLB"},
    {"id": "4380", "name": "NHL"},
    {"id": "4468", "name": "Formula 1"},
    {"id": "4453", "name": "MotoGP"},
]

OUTPUT_FILE = "matches.json"
API_KEY = "3"  # Free tier key for TheSportsDB (public)

def fetch_upcoming_events(league_id):
    """Fetch next 15 events for a league using the free endpoint."""
    url = f"https://www.thesportsdb.com/api/v1/json/{API_KEY}/eventsnextleague.php"
    params = {"id": league_id}
    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return data.get("events") or []
    except Exception as e:
        print(f"   ⚠️ Error fetching league {league_id}: {e}")
        return []

def filter_upcoming(events, days=7):
    """Keep only events happening within the next `days`."""
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=days)
    upcoming = []
    for ev in events:
        if not ev:
            continue
        timestamp = ev.get("strTimestamp") or ev.get("dateEvent")
        if not timestamp:
            continue
        try:
            if "T" in timestamp:
                ev_time = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%S")
            else:
                ev_time = datetime.strptime(timestamp, "%Y-%m-%d")
            ev_time = ev_time.replace(tzinfo=timezone.utc)
            if now <= ev_time <= cutoff:
                upcoming.append(ev)
        except:
            continue
    return upcoming

def main():
    all_matches = []
    for league in LEAGUES:
        print(f"📡 Fetching {league['name']}...")
        events = fetch_upcoming_events(league["id"])
        if not events:
            print(f"   No events found.")
            continue
        upcoming = filter_upcoming(events)
        # ✅ Only add a helper field; do NOT overwrite strLeague
        for ev in upcoming:
            ev["fetched_league"] = league["name"]
        all_matches.extend(upcoming)
        print(f"   ✅ {len(upcoming)} upcoming matches.")

    # Sort by date
    all_matches.sort(key=lambda x: x.get("strTimestamp", x.get("dateEvent", "")))
    
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(all_matches, f, indent=2, ensure_ascii=False)
    
    print(f"\n🎯 Saved {len(all_matches)} matches to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()