#!/usr/bin/env python3
"""
AdwaSport Backend API – Godly Edition (Final)
- Uses real league names from strLeague
- Blacklists non‑sports channels
- Multi‑provider stream capture with relevance scoring
- HLS manifest parsing for quality variants
"""

import json
import os
import logging
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import PlainTextResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import requests
import re

# ---------- Logging ----------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------- Configuration ----------
M3U_URL = "https://raw.githubusercontent.com/amdiyehenok-cmd/AdwaSport-Backend/main/adwa_sports.m3u"
CHANNELS_FILE = "channels.json"
MATCHES_FILE = "matches.json"
CATEGORY_FILE = "categorized_streams.json"

# ---------- Global Data ----------
channels_db = {"channels": []}
matches_db = []
categorized_db = {}

# ---------- Safe Datetime Helpers ----------
def utc_now():
    from datetime import datetime
    return datetime.utcnow()

def utc_now_iso():
    return utc_now().isoformat() + "Z"

# ---------- Data Loading ----------
def load_channels() -> Dict[str, Any]:
    if os.path.exists(CHANNELS_FILE):
        try:
            with open(CHANNELS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load channels: {e}")
    logger.warning("channels.json not found")
    return {"channels": []}

def load_matches() -> List[Dict]:
    if os.path.exists(MATCHES_FILE):
        try:
            with open(MATCHES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load matches: {e}")
    logger.warning("matches.json not found")
    return []

def load_categorized_streams() -> Dict[str, List[Dict]]:
    if os.path.exists(CATEGORY_FILE):
        try:
            with open(CATEGORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load categorized streams: {e}")
    logger.warning("categorized_streams.json not found")
    return {}

# ---------- Lifespan ----------
@asynccontextmanager
async def lifespan(app: FastAPI):
    global channels_db, matches_db, categorized_db
    channels_db = load_channels()
    matches_db = load_matches()
    categorized_db = load_categorized_streams()
    logger.info(f"🚀 AdwaSport Godly API started with {len(channels_db.get('channels', []))} channels, {len(matches_db)} matches, {len(categorized_db)} categories")
    yield
    logger.info("🛑 AdwaSport API shutting down")

# ---------- FastAPI App ----------
app = FastAPI(
    title="AdwaSport API",
    description="Godly sports streaming backend with multi‑provider capture and HLS parsing",
    version="3.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- HLS Manifest Parser ----------
def parse_hls_variants(master_url: str, timeout: int = 8) -> List[Dict]:
    variants = []
    try:
        resp = requests.get(master_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout)
        if resp.status_code != 200:
            return variants
        lines = resp.text.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if line.startswith("#EXT-X-STREAM-INF"):
                bandwidth = re.search(r'BANDWIDTH=(\d+)', line)
                resolution = re.search(r'RESOLUTION=(\d+x\d+)', line)
                codecs = re.search(r'CODECS="([^"]+)"', line)
                i += 1
                if i < len(lines) and not lines[i].startswith('#'):
                    variant_url = lines[i].strip()
                    if not variant_url.startswith('http'):
                        from urllib.parse import urljoin
                        variant_url = urljoin(master_url, variant_url)
                    variants.append({
                        "url": variant_url,
                        "bandwidth": int(bandwidth.group(1)) if bandwidth else None,
                        "resolution": resolution.group(1) if resolution else None,
                        "codecs": codecs.group(1) if codecs else None
                    })
            i += 1
    except Exception as e:
        logger.warning(f"HLS parsing failed for {master_url}: {e}")
    return variants

# ---------- Helper Functions ----------
def get_streams_by_category(category: str) -> List[Dict]:
    cat_lower = category.lower()
    for cat_name, streams in categorized_db.items():
        if cat_name.lower() == cat_lower:
            return streams
    return []

def filter_streams_by_quality(streams: List[Dict], min_height: int) -> List[Dict]:
    filtered = []
    for s in streams:
        res = s.get("resolution")
        if res and "x" in res:
            try:
                h = int(res.split("x")[1])
                if h >= min_height:
                    filtered.append(s)
            except (ValueError, IndexError):
                continue
    return filtered

# ---------- Root & Health ----------
@app.get("/", tags=["Root"])
async def root():
    return {
        "name": "AdwaSport API",
        "version": "3.0.0",
        "status": "online",
        "channels": len(channels_db.get("channels", [])),
        "matches": len(matches_db),
        "categories": list(categorized_db.keys()),
        "total_streams": sum(len(s) for s in categorized_db.values())
    }

@app.get("/health", tags=["Health"])
async def health():
    return {"status": "healthy", "timestamp": utc_now_iso()}

# ---------- Live Playlist ----------
@app.get("/live", tags=["Live"])
async def get_live_playlist():
    try:
        resp = requests.get(M3U_URL, timeout=15)
        resp.raise_for_status()
        return PlainTextResponse(content=resp.text, media_type="application/x-mpegURL")
    except Exception as e:
        logger.error(f"Failed to fetch playlist: {e}")
        raise HTTPException(status_code=503, detail=f"Playlist unavailable: {e}")

# ---------- Matches (Basic) ----------
@app.get("/matches", tags=["Matches"])
async def get_matches(limit: Optional[int] = None):
    matches = load_matches()
    if limit:
        matches = matches[:limit]
    return JSONResponse(content=matches)

@app.get("/matches/today", tags=["Matches"])
async def get_today_matches():
    today = utc_now().date()
    matches = load_matches()
    today_matches = []
    for m in matches:
        ts = m.get("strTimestamp")
        if ts:
            try:
                from datetime import datetime
                match_date = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S").date()
                if match_date == today:
                    today_matches.append(m)
            except:
                pass
    return today_matches

@app.get("/matches/{match_id}", tags=["Matches"])
async def get_match_details(match_id: str):
    matches = load_matches()
    for m in matches:
        if m.get("idEvent") == match_id:
            return m
    raise HTTPException(status_code=404, detail="Match not found")

# ---------- GODLY MATCH-STREAM ENGINE ----------
STREAM_BLACKLIST = [
    "fireplace", "vibes", "replay", "music", "kids", "cooking", "travel",
    "nature", "relax", "ambient", "meditation", "yoga", "pet", "aquarium"
]

@app.get("/matches/{match_id}/streams", tags=["Matches"])
async def get_match_streams(match_id: str, parse_hls: bool = False):
    matches = load_matches()
    match = next((m for m in matches if m.get("idEvent") == match_id), None)
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    
    # ✅ Use the real league name from strLeague
    league = match.get("strLeague", "").lower()
    home = match.get("strHomeTeam", "").lower()
    away = match.get("strAwayTeam", "").lower()
    
    # Build keywords based on the actual league
    keywords = []
    if "premier" in league:
        keywords = ["premier", "epl", "sky sports", "bt sport", "nbc", "peacock", "usa network"]
    elif "la liga" in league:
        keywords = ["la liga", "laliga", "bein", "espn", "movistar", "dazn", "gol tv"]
    elif "serie a" in league:
        keywords = ["serie a", "seriea", "paramount", "cbs", "bein", "dazn", "espn"]
    elif "bundesliga" in league:
        keywords = ["bundesliga", "espn", "sky sports", "dazn", "viaplay"]
    elif "ligue 1" in league:
        keywords = ["ligue 1", "ligue1", "bein", "canal+", "dazn", "fubo"]
    elif "champions" in league:
        keywords = ["champions", "ucl", "bt sport", "cbs", "dazn", "paramount", "bein", "canal+"]
    elif "europa" in league:
        keywords = ["europa", "uel", "bt sport", "dazn", "paramount"]
    else:
        keywords = [league]
    
    keywords.append(home)
    keywords.append(away)
    
    candidate_streams = []
    soccer_streams = categorized_db.get("soccer", [])
    
    for stream in soccer_streams:
        stream_name = stream.get("name", "").lower()
        # Apply blacklist
        if any(bad in stream_name for bad in STREAM_BLACKLIST):
            continue
        
        score = sum(1 for kw in keywords if kw in stream_name)
        if score > 0:
            base_stream = {
                "score": score,
                "id": stream.get("id"),
                "name": stream.get("name"),
                "logo": stream.get("logo"),
                "url": stream.get("url"),
                "quality": stream.get("resolution", "HD"),
                "bitrate": stream.get("bitrate"),
                "latency_ms": stream.get("latency_ms")
            }
            
            if parse_hls and stream.get("url", "").endswith(".m3u8"):
                variants = parse_hls_variants(stream["url"])
                if variants:
                    for v in variants:
                        variant_stream = base_stream.copy()
                        variant_stream["url"] = v["url"]
                        variant_stream["quality"] = v.get("resolution", base_stream["quality"])
                        variant_stream["bitrate"] = v.get("bandwidth")
                        candidate_streams.append(variant_stream)
                else:
                    candidate_streams.append(base_stream)
            else:
                candidate_streams.append(base_stream)
    
    candidate_streams.sort(key=lambda x: x.get("score", 0), reverse=True)
    for s in candidate_streams:
        s.pop("score", None)
    
    return {
        "match": match,
        "streams": candidate_streams[:20],
        "total_available": len(candidate_streams)
    }

# ---------- Streams & Categories (Premium) ----------
@app.get("/streams", tags=["Streams"])
async def get_all_streams():
    return JSONResponse(content=channels_db)

@app.get("/streams/search", tags=["Streams"])
async def search_streams(q: str = Query(..., min_length=1)):
    results = [ch for ch in channels_db.get("channels", []) if q.lower() in ch["name"].lower()]
    return results

@app.get("/api/categories", tags=["Premium"])
async def get_categories():
    return {cat: len(streams) for cat, streams in categorized_db.items()}

@app.get("/api/live-streams", tags=["Premium"])
async def get_live_streams(
    category: Optional[str] = None,
    quality: Optional[str] = None,
    limit: Optional[int] = None
):
    if category:
        streams = get_streams_by_category(category)
        if not streams:
            raise HTTPException(status_code=404, detail=f"Category '{category}' not found")
    else:
        streams = []
        for cat_streams in categorized_db.values():
            streams.extend(cat_streams)
    
    if quality:
        try:
            min_h = int(quality)
            streams = filter_streams_by_quality(streams, min_h)
        except ValueError:
            raise HTTPException(status_code=400, detail="Quality must be an integer (e.g., 720)")
    
    if limit:
        streams = streams[:limit]
    
    return {"streams": streams, "count": len(streams)}

@app.get("/api/soccer-streams", tags=["Premium"])
async def get_soccer_streams(quality: Optional[str] = None):
    streams = get_streams_by_category("soccer")
    if quality:
        try:
            min_h = int(quality)
            streams = filter_streams_by_quality(streams, min_h)
        except ValueError:
            raise HTTPException(status_code=400, detail="Quality must be an integer")
    return {"streams": streams, "count": len(streams)}

@app.get("/api/basketball-streams", tags=["Premium"])
async def get_basketball_streams():
    streams = get_streams_by_category("basketball")
    return {"streams": streams, "count": len(streams)}

@app.get("/api/american-football-streams", tags=["Premium"])
async def get_american_football_streams():
    streams = get_streams_by_category("american_football")
    return {"streams": streams, "count": len(streams)}

@app.get("/api/baseball-streams", tags=["Premium"])
async def get_baseball_streams():
    streams = get_streams_by_category("baseball")
    return {"streams": streams, "count": len(streams)}

@app.get("/api/hockey-streams", tags=["Premium"])
async def get_hockey_streams():
    streams = get_streams_by_category("hockey")
    return {"streams": streams, "count": len(streams)}

@app.get("/api/motorsport-streams", tags=["Premium"])
async def get_motorsport_streams():
    streams = get_streams_by_category("motorsport")
    return {"streams": streams, "count": len(streams)}

@app.get("/api/combat-streams", tags=["Premium"])
async def get_combat_streams():
    streams = get_streams_by_category("combat")
    return {"streams": streams, "count": len(streams)}

@app.get("/api/cricket-streams", tags=["Premium"])
async def get_cricket_streams():
    streams = get_streams_by_category("cricket")
    return {"streams": streams, "count": len(streams)}

@app.get("/api/tennis-streams", tags=["Premium"])
async def get_tennis_streams():
    streams = get_streams_by_category("tennis")
    return {"streams": streams, "count": len(streams)}

@app.get("/api/golf-streams", tags=["Premium"])
async def get_golf_streams():
    streams = get_streams_by_category("golf")
    return {"streams": streams, "count": len(streams)}

@app.get("/api/stream/{stream_id}", tags=["Premium"])
async def get_stream_details(stream_id: str):
    for cat_streams in categorized_db.values():
        for s in cat_streams:
            if s.get("id") == stream_id:
                return s
    raise HTTPException(status_code=404, detail="Stream not found")

# ---------- Channels & Leagues ----------
@app.get("/channels", tags=["Channels"])
async def get_channels():
    return JSONResponse(content=channels_db)

@app.get("/leagues", tags=["Leagues"])
async def get_leagues():
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
    q_lower = q.lower()
    results = {"matches": [], "channels": []}
    for m in load_matches():
        if (q_lower in m.get("strEvent", "").lower() or
            q_lower in m.get("strHomeTeam", "").lower() or
            q_lower in m.get("strAwayTeam", "").lower()):
            results["matches"].append(m)
    for ch in channels_db.get("channels", []):
        if q_lower in ch["name"].lower():
            results["channels"].append(ch)
    return results

# ---------- Admin ----------
@app.post("/admin/refresh", tags=["Admin"])
async def refresh_data():
    global channels_db, matches_db, categorized_db
    channels_db = load_channels()
    matches_db = load_matches()
    categorized_db = load_categorized_streams()
    logger.info("Data reloaded via admin endpoint")
    return {
        "status": "refreshed",
        "channels": len(channels_db.get("channels", [])),
        "matches": len(matches_db),
        "categories": len(categorized_db)
    }

# ---------- Run ----------
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)