#!/usr/bin/env python3
"""
AdwaSport Godly Football Intelligence Engine
- Deep stream validation (HTTP + ffprobe)
- Quality scoring (resolution, bitrate, latency)
- League detection (Premier League, La Liga, etc.)
- Top‑league prioritisation
- Composite ranking score
- Sources: iptv-org + DaddyLive + local
"""

import requests
import re
import time
import subprocess
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import OrderedDict, defaultdict
from typing import List, Tuple, Optional, Dict, Any

# ============================================
# CONFIGURATION – FOOTBALL ONLY
# ============================================

SPORT_CATEGORIES = {
    "soccer": {
        "keywords": [
            "premier league", "epl", "la liga", "laliga", "serie a", "bundesliga",
            "ligue 1", "champions league", "ucl", "europa league", "uel",
            "mls", "eredivisie", "primeira liga", "sky sports", "bt sport",
            "tnt sports", "nbc sports", "peacock", "cbs sports", "paramount+",
            "espn", "fox sports", "bein sports", "dazn", "fubo", "sling",
            "youtube tv", "hulu", "movistar", "gol tv", "espn deportes",
            "tyc sports", "directv", "bein", "alkass", "abu dhabi sports",
            "dubai sports", "super sport", "optus sport", "star sports",
            "sony ten", "willow", "viaplay", "eleven sports", "sport tv",
            "polsat", "canal+", "soccer", "football"
        ],
        "top_leagues": [
            "premier league", "la liga", "serie a", "bundesliga", "ligue 1",
            "champions league", "europa league"
        ]
    }
}

# Exclude keywords (non‑sports)
EXCLUDE_KEYWORDS = [
    "mtv", "pluto tv", "nick", "disney", "cartoon", "kids", "cooking",
    "food", "travel", "music", "comedy", "drama", "reality", "news",
    "bloomberg", "cnbc", "cnn", "fox news", "msnbc", "bbc", "weather",
    "shopping", "religion", "christian", "islam", "quran", "church",
    "fireplace", "vibes", "ambient", "meditation"
]

INPUT_FILES = [
    "https://iptv-org.github.io/iptv/categories/sports.m3u",
    "https://dlhd.so/playlist.m3u",
    "combined-playlist.m3u",
]

OUTPUT_FILE = "adwa_sports.m3u"
CATEGORY_OUTPUT = "categorized_streams.json"

VALIDATION_TIMEOUT = 8
MAX_WORKERS = 30
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

# ============================================
# REMOTE M3U FETCH
# ============================================

def fetch_remote_m3u(url: str) -> List[str]:
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
        resp.raise_for_status()
        return resp.text.splitlines()
    except Exception as e:
        print(f"⚠️ Failed to fetch {url}: {e}")
        return []

# ============================================
# QUALITY SCORING
# ============================================

def compute_quality_score(resolution: Optional[str], bitrate: Optional[str]) -> float:
    score = 0.0
    if resolution:
        match = re.search(r'(\d+)x(\d+)', resolution)
        if match:
            h = int(match.group(2))
            if h >= 1080:   score += 60
            elif h >= 720:  score += 40
            elif h >= 480:  score += 20
    if bitrate:
        try:
            br = int(bitrate) / 1_000_000
            if br >= 5:      score += 30
            elif br >= 2.5:  score += 20
            elif br >= 1:    score += 10
        except (ValueError, TypeError):
            pass
    return min(score, 100.0)

def compute_latency_score(latency_ms: Optional[int]) -> float:
    if latency_ms is None:    return 50.0
    if latency_ms < 200:      return 100.0
    if latency_ms < 500:      return 80.0
    if latency_ms < 1000:     return 50.0
    return 20.0

def detect_leagues(channel_name: str) -> List[str]:
    name_lower = channel_name.lower()
    leagues = []
    for league in SPORT_CATEGORIES["soccer"]["top_leagues"]:
        if league in name_lower:
            leagues.append(league)
    return leagues

def compute_league_boost(leagues: List[str]) -> float:
    if not leagues:
        return 0.0
    return min(len(leagues) * 15.0, 30.0)

# ============================================
# STREAM VALIDATION
# ============================================

def validate_stream_deep(url: str) -> Dict[str, Any]:
    result = {
        "url": url, "alive": False, "http_status": None,
        "latency_ms": 0, "resolution": None, "bitrate": None,
        "codec": None, "error": None
    }
    start = time.time()
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT},
                            stream=True, timeout=VALIDATION_TIMEOUT)
        result["http_status"] = resp.status_code
        if resp.status_code != 200:
            result["error"] = f"HTTP {resp.status_code}"
            return result

        chunk = next(resp.iter_content(2048), b'')
        result["latency_ms"] = int((time.time() - start) * 1000)
        if b'#EXTM3U' not in chunk and b'<?xml' not in chunk:
            result["error"] = "Invalid playlist format"
            return result

        try:
            cmd = ["ffprobe", "-v", "quiet", "-print_format", "json",
                   "-show_streams", "-show_format", "-timeout",
                   str(VALIDATION_TIMEOUT * 1000000), url]
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=VALIDATION_TIMEOUT+5)
            if proc.returncode == 0:
                data = json.loads(proc.stdout)
                for stream in data.get("streams", []):
                    if stream.get("codec_type") == "video":
                        result["resolution"] = f"{stream.get('width')}x{stream.get('height')}"
                        result["codec"] = stream.get("codec_name")
                        result["bitrate"] = stream.get("bit_rate")
                        break
                result["alive"] = True
            else:
                result["alive"] = True
                result["error"] = "ffprobe failed, stream may be playable"
        except (subprocess.TimeoutExpired, FileNotFoundError):
            result["alive"] = True
    except Exception as e:
        result["error"] = str(e)
    return result

# ============================================
# CHANNEL DETECTION
# ============================================

def is_soccer_channel(name: str) -> bool:
    name_lower = name.lower()
    if any(ex in name_lower for ex in EXCLUDE_KEYWORDS):
        return False
    return any(kw in name_lower for kw in SPORT_CATEGORIES["soccer"]["keywords"])

# ============================================
# M3U PARSING
# ============================================

def parse_m3u(source: str) -> List[Tuple[str, str, Dict]]:
    channels = []
    if source.startswith("http://") or source.startswith("https://"):
        lines = fetch_remote_m3u(source)
        if not lines:
            return []
    else:
        try:
            with open(source, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
        except FileNotFoundError:
            return []

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith('#EXTINF'):
            extinf = line
            vlcopts = []
            i += 1
            while i < len(lines) and lines[i].startswith('#EXTVLCOPT'):
                vlcopts.append(lines[i].strip())
                i += 1
            if i < len(lines) and not lines[i].startswith('#'):
                url = lines[i].strip()
                meta = {
                    'vlcopts': vlcopts,
                    'tvg_id': re.search(r'tvg-id="([^"]+)"', extinf),
                    'tvg_logo': re.search(r'tvg-logo="([^"]+)"', extinf),
                    'group': re.search(r'group-title="([^"]+)"', extinf)
                }
                channels.append((extinf, url, meta))
            i += 1
        else:
            i += 1
    return channels

# ============================================
# MAIN
# ============================================

def main():
    print("🚀 AdwaSport Godly Football Intelligence Engine")
    all_channels = OrderedDict()
    seen_urls = set()

    for f in INPUT_FILES:
        print(f"📂 {f}...")
        for extinf, url, meta in parse_m3u(f):
            if url in seen_urls:
                continue
            seen_urls.add(url)
            name_match = re.search(r',([^,]+)$', extinf)
            if not name_match:
                continue
            name = name_match.group(1).strip()
            if not is_soccer_channel(name):
                continue
            key = meta['tvg_id'].group(1) if meta['tvg_id'] else name.lower()
            if key not in all_channels:
                all_channels[key] = (extinf, url, meta, name)

    print(f"\n🎯 Found {len(all_channels)} soccer channels. Validating & scoring...")

    validated = OrderedDict()
    soccer_streams = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(validate_stream_deep, data[1]): key
                   for key, data in all_channels.items()}
        for i, f in enumerate(as_completed(futures), 1):
            key = futures[f]
            extinf, url, meta, name = all_channels[key]
            result = f.result()

            if result["alive"]:
                leagues = detect_leagues(name)
                quality_score = compute_quality_score(result.get("resolution"),
                                                      result.get("bitrate"))
                latency_score = compute_latency_score(result.get("latency_ms"))
                league_boost = compute_league_boost(leagues)

                total_score = (quality_score * 0.5 +
                               latency_score * 0.3 +
                               league_boost * 0.2)

                stream_info = {
                    "id": key,
                    "name": name,
                    "url": url,
                    "logo": meta['tvg_logo'].group(1) if meta['tvg_logo'] else "",
                    "resolution": result.get("resolution"),
                    "bitrate": result.get("bitrate"),
                    "latency_ms": result.get("latency_ms"),
                    "sport": "soccer",
                    "leagues": leagues,
                    "quality_score": round(quality_score, 1),
                    "latency_score": round(latency_score, 1),
                    "league_boost": round(league_boost, 1),
                    "total_score": round(total_score, 1)
                }

                validated[key] = (extinf, url, meta, name, result, stream_info)
                soccer_streams.append(stream_info)

                print(f"   [{i}/{len(all_channels)}] ✅ {name} score={total_score:.1f}")
            else:
                print(f"   [{i}/{len(all_channels)}] ❌ {name} - {result.get('error')}")

    # Sort by total score
    soccer_streams.sort(key=lambda x: x["total_score"], reverse=True)

    # Write M3U
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write("#EXTM3U\n")
        for stream in soccer_streams:
            key = stream["id"]
            extinf, url, meta, name, _, _ = validated[key]
            f.write(f"{extinf}\n")
            for opt in meta['vlcopts']:
                f.write(f"{opt}\n")
            f.write(f"{url}\n")

    # Write categorized JSON (only soccer)
    with open(CATEGORY_OUTPUT, 'w', encoding='utf-8') as f:
        json.dump({"soccer": soccer_streams}, f, indent=2)

    print(f"\n💾 Saved {len(soccer_streams)} soccer streams to {OUTPUT_FILE}")
    print(f"📊 Categorized data saved to {CATEGORY_OUTPUT}")

if __name__ == "__main__":
    main()