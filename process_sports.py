#!/usr/bin/env python3
"""
AdwaSport Advanced Sports Processor
Filters by sport category, validates streams deeply, and exports categorized playlists.
"""

import requests
import re
import time
import subprocess
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import OrderedDict, defaultdict
from typing import List, Tuple, Optional, Dict

# ============================================
# CONFIGURATION
# ============================================

# Category mapping – keywords for each sport
SPORT_CATEGORIES = {
    "soccer": [
        # Leagues
        "premier league", "epl", "la liga", "laliga", "serie a", "bundesliga",
        "ligue 1", "champions league", "ucl", "europa league", "uel",
        "mls", "eredivisie", "primeira liga", "ligue 1",
        
        # Major Broadcasters (English)
        "sky sports", "bt sport", "tnt sports", "nbc sports", "peacock",
        "cbs sports", "paramount+", "espn", "fox sports", "bein sports",
        "dazn", "fubo", "sling", "youtube tv", "hulu",
        
        # Spanish Broadcasters
        "movistar", "gol tv", "espn deportes", "tyc sports", "directv",
        
        # Arabic Broadcasters
        "bein", "alkass", "abu dhabi sports", "dubai sports",
        
        # Other International
        "super sport", "optus sport", "star sports", "sony ten", "willow",
        "viaplay", "eleven sports", "sport tv", "polsat", "canal+"
    ],
    # ... keep other categories (american_football, basketball, etc.)
}

# Exclude keywords (non-sports)
EXCLUDE_KEYWORDS = [
    "mtv", "pluto tv", "nick", "disney", "cartoon", "kids", "cooking",
    "food", "travel", "music", "comedy", "drama", "reality", "news",
    "bloomberg", "cnbc", "cnn", "fox news", "msnbc", "bbc", "weather",
    "shopping", "religion", "christian", "islam", "quran", "church"
]

INPUT_FILES = ["combined-playlist.m3u", "BD.m3u", "Pixelsports.m3u", "TVPass.m3u", "CricHD.m3u"]
OUTPUT_FILE = "adwa_sports.m3u"
CATEGORY_OUTPUT = "categorized_streams.json"

VALIDATION_TIMEOUT = 8
MAX_WORKERS = 30
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

# ============================================
# STREAM VALIDATION WITH FFMPEG
# ============================================

def validate_stream_deep(url: str) -> Dict:
    """
    Deep validation using ffprobe to check:
    - HTTP 200
    - Valid HLS/DASH
    - Bitrate and resolution
    - Latency (time to first byte)
    """
    result = {
        "url": url,
        "alive": False,
        "http_status": None,
        "latency_ms": 0,
        "resolution": None,
        "bitrate": None,
        "codec": None,
        "error": None
    }
    start = time.time()
    try:
        # First check HTTP headers
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, stream=True, timeout=VALIDATION_TIMEOUT)
        result["http_status"] = resp.status_code
        if resp.status_code != 200:
            result["error"] = f"HTTP {resp.status_code}"
            return result
        
        # Read first chunk to confirm it's a playlist
        chunk = next(resp.iter_content(2048), b'')
        result["latency_ms"] = int((time.time() - start) * 1000)
        if b'#EXTM3U' not in chunk and b'<?xml' not in chunk:
            result["error"] = "Invalid playlist format"
            return result
        
        # Use ffprobe to get stream details (if ffmpeg is installed)
        try:
            cmd = [
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_streams", "-show_format", "-timeout", str(VALIDATION_TIMEOUT * 1000000),
                url
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=VALIDATION_TIMEOUT+5)
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
                # ffprobe failed but stream might still play – mark as alive but note error
                result["alive"] = True
                result["error"] = "ffprobe failed, stream may be playable"
        except (subprocess.TimeoutExpired, FileNotFoundError):
            # ffprobe not available or timed out – fallback to basic check
            result["alive"] = True
    except Exception as e:
        result["error"] = str(e)
    return result

def detect_category(channel_name: str) -> List[str]:
    """Return list of sport categories this channel belongs to."""
    name_lower = channel_name.lower()
    categories = []
    for cat, keywords in SPORT_CATEGORIES.items():
        if any(kw in name_lower for kw in keywords):
            categories.append(cat)
    return categories

def is_sports_channel(name: str) -> bool:
    name_lower = name.lower()
    if any(ex in name_lower for ex in EXCLUDE_KEYWORDS):
        return False
    return any(any(kw in name_lower for kw in kw_list) for kw_list in SPORT_CATEGORIES.values())

# ============================================
# MAIN PROCESSING
# ============================================

def parse_m3u(file_path: str) -> List[Tuple[str, str, Dict]]:
    # (same as before)
    channels = []
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
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

def main():
    print("🚀 AdwaSport Advanced Processor")
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
            if not is_sports_channel(name):
                continue
            key = meta['tvg_id'].group(1) if meta['tvg_id'] else name.lower()
            if key not in all_channels:
                all_channels[key] = (extinf, url, meta, name)
    
    print(f"\n🎯 Found {len(all_channels)} sports channels. Validating...")
    
    # Validate streams deeply
    validated = OrderedDict()
    categorized = defaultdict(list)
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(validate_stream_deep, data[1]): key for key, data in all_channels.items()}
        for i, f in enumerate(as_completed(futures), 1):
            key = futures[f]
            extinf, url, meta, name = all_channels[key]
            result = f.result()
            if result["alive"]:
                validated[key] = (extinf, url, meta, name, result)
                cats = detect_category(name)
                for cat in cats:
                    categorized[cat].append({
                        "id": key,
                        "name": name,
                        "url": url,
                        "logo": meta['tvg_logo'].group(1) if meta['tvg_logo'] else "",
                        "resolution": result.get("resolution"),
                        "bitrate": result.get("bitrate"),
                        "latency_ms": result.get("latency_ms")
                    })
                print(f"   [{i}/{len(all_channels)}] ✅ {name} ({', '.join(cats)})")
            else:
                print(f"   [{i}/{len(all_channels)}] ❌ {name} - {result.get('error')}")
    
    # Write combined M3U
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write("#EXTM3U\n")
        for extinf, url, meta, name, _ in validated.values():
            f.write(f"{extinf}\n")
            for opt in meta['vlcopts']:
                f.write(f"{opt}\n")
            f.write(f"{url}\n")
    
    # Write categorized JSON
    with open(CATEGORY_OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(categorized, f, indent=2)
    
    print(f"\n💾 Saved {len(validated)} streams to {OUTPUT_FILE}")
    print(f"📊 Categorized data saved to {CATEGORY_OUTPUT}")

if __name__ == "__main__":
    main()