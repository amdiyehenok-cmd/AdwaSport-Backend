#!/usr/bin/env python3
"""
AdwaSport Sports Playlist Processor
Filters, deduplicates, and validates sports channels from multiple M3U sources.
Designed to run inside GitHub Actions or locally.
"""

import requests
import re
import time
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse
from collections import OrderedDict
from typing import List, Tuple, Optional, Dict

# ============================================
# CONFIGURATION – ADJUST AS NEEDED
# ============================================

# Keywords to identify sports channels (lowercase)
SPORTS_KEYWORDS = [
    "sport", "espn", "bein", "premier", "la liga", "serie a", "bundesliga",
    "uefa", "champions", "europa", "nba", "nfl", "mlb", "nhl", "f1", "formula",
    "motogp", "ufc", "wwe", "cricket", "tennis", "golf", "football", "soccer",
    "basketball", "baseball", "hockey", "racing", "boxing", "olympic",
    "liga", "cup", "match", "live", "tv", "hd", "sky sports", "bt sport",
    "dazn", "fox sports", "nbc sports", "cbs sports", "tsn", "sportsnet"
]

# Channels to always include even if name doesn't match (e.g., generic names)
ALWAYS_INCLUDE = [
    "bein sports", "sky sports", "bt sport", "dazn", "espn", "fox sports"
]

# M3U files to process (relative paths or absolute)
INPUT_FILES = [
    "combined-playlist.m3u",
    "BD.m3u",
    "Pixelsports.m3u",
    "TVPass.m3u",
    "CricHD.m3u",
    "SportsWebcast.m3u",
    "FSTV24.m3u8",
    "hilaytv.m3u",
    "klowdtv.m3u",
    "Moveonjoy.m3u",
    "SOFAST.m3u",
    "TheTVApp.m3u8",
    "UDPTV.m3u",
    "v2hcdn.m3u",
    "Wnslive.m3u",
    "Yupptv.m3u"
]

# Output file
OUTPUT_FILE = "adwa_sports.m3u"

# Validation settings
VALIDATE_STREAMS = True
MAX_VALIDATION_WORKERS = 30          # Number of parallel checks
VALIDATION_TIMEOUT = 5               # Seconds per stream
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# ============================================
# CORE LOGIC
# ============================================

def normalize_channel_name(name: str) -> str:
    """Strip tags and clean channel name for comparison."""
    # Remove common prefixes/suffixes and extra info
    name = re.sub(r'\(.*?\)|\[.*?\]|HD|SD|FHD|UHD|4K', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\s+', ' ', name).strip().lower()
    return name

def extract_tvg_id(line: str) -> Optional[str]:
    """Extract tvg-id from #EXTINF line if present."""
    match = re.search(r'tvg-id="([^"]+)"', line)
    return match.group(1) if match else None

def extract_tvg_logo(line: str) -> Optional[str]:
    """Extract tvg-logo from #EXTINF line if present."""
    match = re.search(r'tvg-logo="([^"]+)"', line)
    return match.group(1) if match else None

def extract_group_title(line: str) -> Optional[str]:
    """Extract group-title from #EXTINF line."""
    match = re.search(r'group-title="([^"]+)"', line)
    return match.group(1) if match else None

def is_sports_channel(name: str) -> bool:
    """Determine if a channel is sports-related."""
    name_lower = name.lower()
    # Always include if any keyword matches
    if any(kw in name_lower for kw in SPORTS_KEYWORDS):
        return True
    # Also include specific always-include patterns
    if any(inc in name_lower for inc in ALWAYS_INCLUDE):
        return True
    return False

def parse_m3u(file_path: str) -> List[Tuple[str, str, Dict]]:
    """
    Parse an M3U file and return list of (extinf_line, url, metadata).
    Handles #EXTVLCOPT lines properly.
    """
    channels = []
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"⚠️  File not found: {file_path}")
        return []

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith('#EXTINF'):
            extinf_line = line
            # Gather any #EXTVLCOPT lines that follow
            vlcopts = []
            i += 1
            while i < len(lines) and lines[i].startswith('#EXTVLCOPT'):
                vlcopts.append(lines[i].strip())
                i += 1
            # The stream URL should be next non-comment line
            if i < len(lines) and not lines[i].startswith('#'):
                url = lines[i].strip()
                metadata = {
                    'vlcopts': vlcopts,
                    'tvg_id': extract_tvg_id(extinf_line),
                    'tvg_logo': extract_tvg_logo(extinf_line),
                    'group': extract_group_title(extinf_line)
                }
                channels.append((extinf_line, url, metadata))
            i += 1
        else:
            i += 1
    return channels

def validate_stream(url: str, timeout: int = VALIDATION_TIMEOUT) -> bool:
    """Check if a stream URL is reachable and returns 200 OK."""
    try:
        headers = {'User-Agent': USER_AGENT}
        # Only fetch headers (stream=True prevents downloading the whole stream)
        resp = requests.get(url, headers=headers, stream=True, timeout=timeout)
        # Check for success status and if content looks like a playlist
        if resp.status_code == 200:
            # Peek at first few bytes to see if it's an M3U8 or MPD
            first_chunk = next(resp.iter_content(1024), b'')
            content_preview = first_chunk[:200].decode('utf-8', errors='ignore')
            if '#EXTM3U' in content_preview or '<?xml' in content_preview:
                return True
        return False
    except Exception:
        return False

def process_all_playlists() -> OrderedDict:
    """
    Read all input playlists, filter sports channels, and deduplicate.
    Returns an OrderedDict keyed by (normalized_name or tvg_id) with best entry.
    """
    all_channels = OrderedDict()
    seen_urls = set()

    for file_path in INPUT_FILES:
        print(f"📂 Processing {file_path}...")
        channels = parse_m3u(file_path)
        print(f"   Found {len(channels)} channels")

        for extinf, url, meta in channels:
            # Skip if URL already seen
            if url in seen_urls:
                continue
            seen_urls.add(url)

            # Extract channel name (text after last comma in EXTINF)
            name_match = re.search(r',([^,]+)$', extinf)
            if not name_match:
                continue
            channel_name = name_match.group(1).strip()

            # Filter sports
            if not is_sports_channel(channel_name):
                continue

            # Create unique key: prefer tvg_id, else normalized name
            key = meta['tvg_id'] if meta['tvg_id'] else normalize_channel_name(channel_name)
            if not key:
                key = url  # fallback

            # Keep only the first occurrence (or could prioritize by source)
            if key not in all_channels:
                all_channels[key] = (extinf, url, meta, channel_name)

    print(f"\n✅ Total unique sports channels after deduplication: {len(all_channels)}")
    return all_channels

def validate_and_filter(all_channels: OrderedDict) -> OrderedDict:
    """Validate streams in parallel and keep only working ones."""
    if not VALIDATE_STREAMS:
        return all_channels

    print(f"\n🔍 Validating {len(all_channels)} streams with {MAX_VALIDATION_WORKERS} workers...")
    valid_channels = OrderedDict()
    total = len(all_channels)
    completed = 0

    with ThreadPoolExecutor(max_workers=MAX_VALIDATION_WORKERS) as executor:
        future_to_key = {
            executor.submit(validate_stream, data[1]): key
            for key, data in all_channels.items()
        }

        for future in as_completed(future_to_key):
            key = future_to_key[future]
            extinf, url, meta, name = all_channels[key]
            completed += 1
            try:
                if future.result():
                    valid_channels[key] = all_channels[key]
                    print(f"   [{completed}/{total}] ✅ {name[:50]}")
                else:
                    print(f"   [{completed}/{total}] ❌ {name[:50]}")
            except Exception as e:
                print(f"   [{completed}/{total}] ⚠️  {name[:50]} - {e}")

    print(f"\n🎯 Alive streams: {len(valid_channels)}")
    return valid_channels

def write_m3u(channels: OrderedDict, output_path: str):
    """Write the final M3U playlist with proper formatting."""
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write("#EXTM3U\n")
        for key, (extinf, url, meta, name) in channels.items():
            # Write the EXTINF line
            f.write(f"{extinf}\n")
            # Write any VLC options
            for opt in meta['vlcopts']:
                f.write(f"{opt}\n")
            # Write the URL
            f.write(f"{url}\n")
    print(f"💾 Playlist saved to {output_path}")

def main():
    start_time = time.time()
    print("🚀 AdwaSport Sports Playlist Processor")
    print("=======================================")

    # Step 1: Parse and filter
    all_sports = process_all_playlists()

    if not all_sports:
        print("❌ No sports channels found. Exiting.")
        sys.exit(1)

    # Step 2: Validate (optional)
    final_channels = validate_and_filter(all_sports)

    # Step 3: Write output
    write_m3u(final_channels, OUTPUT_FILE)

    elapsed = time.time() - start_time
    print(f"\n⏱️  Completed in {elapsed:.2f} seconds")
    print(f"📡 Final playlist contains {len(final_channels)} working sports channels.")

if __name__ == "__main__":
    main()