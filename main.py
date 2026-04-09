#!/usr/bin/env python3
"""
AdwaSport Backend API
Serves live sports playlist, match data, and channel streams.
"""

import json
import os
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import PlainTextResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import requests
from typing import Optional, List

app = FastAPI(
    title="AdwaSport API",
    description="Premium sports streaming backend",
    version="1.0.0"
)

# Enable CORS for Flutter app
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration
M3U_URL = "https://raw.githubusercontent.com/henokamdiye/IPTV-Scraper-Zilla/main/adwa_sports.m3u"
CHANNELS_FILE = "channels.json"
MATCHES_FILE = "matches.json"

# Load data at startup
def load_channels():
    if os.path.exists(CHANNELS_FILE):
        with open(CHANNELS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"channels": []}

def load_matches():
    if os.path.exists(MATCHES_FILE):
        with open(MATCHES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

channels_db = load_channels()
matches_db = load_matches()

@app.get("/", tags=["Root"])
async def root():
    return {
        "name": "AdwaSport API",
        "version": "1.0.0",
        "status": "online",
        "channels": len(channels_db.get("channels", [])),
        "matches": len(matches_db)
    }

@app.get("/live", tags=["Live"])
async def get_live_playlist():
    """Return the raw M3U playlist of working sports streams."""
    try:
        resp = requests.get(M3U_URL, timeout=15)
        resp.raise_for_status()
        return PlainTextResponse(content=resp.text, media_type="application/x-mpegURL")
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Playlist unavailable: {e}")

@app.get("/matches", tags=["Matches"])
async def get_matches(limit: Optional[int] = None):
    """Return upcoming sports events."""
    matches = load_matches()  # Reload to get fresh data
    if limit:
        matches = matches[:limit]
    return JSONResponse(content=matches)

@app.get("/matches/today", tags=["Matches"])
async def get_today_matches():
    """Return matches scheduled for today."""
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).date()
    matches = load_matches()
    today_matches = []
    for m in matches:
        ts = m.get("strTimestamp")
        if ts:
            try:
                match_date = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S").date()
                if match_date == today:
                    today_matches.append(m)
            except:
                pass
    return today_matches

@app.get("/matches/{match_id}", tags=["Matches"])
async def get_match_details(match_id: str):
    """Get detailed information for a specific match."""
    matches = load_matches()
    for m in matches:
        if m.get("idEvent") == match_id:
            return m
    raise HTTPException(status_code=404, detail="Match not found")

@app.get("/matches/{match_id}/streams", tags=["Matches"])
async def get_match_streams(match_id: str):
    """Get available streams for a specific match."""
    matches = load_matches()
    match = next((m for m in matches if m.get("idEvent") == match_id), None)
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    
    # Simple keyword mapping (will be enhanced later)
    league = match.get("league_name", "").lower()
    keywords = [league]
    if "premier" in league:
        keywords = ["premier league", "epl", "sky sports", "nbc sports"]
    elif "champions" in league:
        keywords = ["champions league", "ucl", "bt sport", "cbs sports"]
    elif "nba" in league:
        keywords = ["nba", "nba tv", "espn"]
    
    streams = []
    for ch in channels_db.get("channels", []):
        ch_name = ch["name"].lower()
        if any(kw in ch_name for kw in keywords):
            streams.append({
                "channel_id": ch["id"],
                "channel_name": ch["name"],
                "logo": ch.get("logo", ""),
                "url": ch["url"],
                "quality": "HD",
                "language": "English"
            })
    
    return {
        "match": match,
        "streams": streams[:10]  # Limit to top 10
    }

@app.get("/streams", tags=["Streams"])
async def get_all_streams():
    """Return all sports channels with metadata."""
    return JSONResponse(content=channels_db)

@app.get("/streams/search", tags=["Streams"])
async def search_streams(q: str = Query(..., min_length=1)):
    """Search channels by name."""
    results = [ch for ch in channels_db.get("channels", []) if q.lower() in ch["name"].lower()]
    return results

@app.get("/streams/health", tags=["Streams"])
async def get_stream_health():
    """Get health status of streams."""
    # Simple placeholder - can be enhanced with actual validation
    return {"status": "operational", "alive": len(channels_db.get("channels", [])), "dead": 0}

@app.get("/channels", tags=["Channels"])
async def get_channels():
    """Alias for /streams."""
    return JSONResponse(content=channels_db)

@app.get("/leagues", tags=["Leagues"])
async def get_leagues():
    """Return list of supported leagues."""
    leagues = [
        {"id": "4328", "name": "English Premier League", "country": "England"},
        {"id": "4330", "name": "La Liga", "country": "Spain"},
        {"id": "4332", "name": "Serie A", "country": "Italy"},
        {"id": "4331", "name": "Bundesliga", "country": "Germany"},
        {"id": "4334", "name": "Ligue 1", "country": "France"},
        {"id": "4480", "name": "UEFA Champions League", "country": "Europe"},
        {"id": "4481", "name": "UEFA Europa League", "country": "Europe"},
        {"id": "4387", "name": "NBA", "country": "USA"},
        {"id": "4391", "name": "NFL", "country": "USA"},
        {"id": "4468", "name": "Formula 1", "country": "World"}
    ]
    return leagues

@app.get("/search", tags=["Search"])
async def global_search(q: str = Query(..., min_length=1)):
    """Search across matches and channels."""
    results = {
        "matches": [],
        "channels": []
    }
    q_lower = q.lower()
    for m in load_matches():
        if q_lower in m.get("strEvent", "").lower() or q_lower in m.get("strHomeTeam", "").lower() or q_lower in m.get("strAwayTeam", "").lower():
            results["matches"].append(m)
    for ch in channels_db.get("channels", []):
        if q_lower in ch["name"].lower():
            results["channels"].append(ch)
    return results

@app.post("/admin/refresh", tags=["Admin"])
async def refresh_data():
    """Reload data files."""
    global channels_db, matches_db
    channels_db = load_channels()
    matches_db = load_matches()
    return {"status": "refreshed", "channels": len(channels_db["channels"]), "matches": len(matches_db)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)