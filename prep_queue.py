#!/usr/bin/env python3
"""
🎯 PREP QUEUE - Smart queue preparation
- Smart fetch: only add new anime, don't refetch everything
- Category filter: TV/Movie/OVA/ONA/Special based on showType
- In-progress tracking: avoid duplicate processing
- Sorted by episode count (smallest first)
"""
import os
import sys
import argparse

TERMUX_PYTHON = "/data/data/com.termux/files/usr/bin/python3"
if os.path.exists(TERMUX_PYTHON):
    if sys.executable.startswith("/usr/bin/python") or sys.executable.startswith("/bin/python") or sys.executable.startswith("/usr/local/bin/python"):
        import subprocess
        result = subprocess.run([TERMUX_PYTHON] + sys.argv)
        sys.exit(result.returncode)

import json
import time
import requests
from datetime import datetime

ANIWATCH_API = "https://aniwatch-co-at-api.vercel.app"
TRACKING_DIR = os.path.expanduser("~/pipeline/tracking")
QUEUE_FILE = os.path.join(TRACKING_DIR, "queue.txt")
MASTER_FILE = os.path.join(TRACKING_DIR, "master.json")
IN_PROGRESS_FILE = os.path.join(TRACKING_DIR, "in_progress.txt")
LOG_FILE = os.path.join(TRACKING_DIR, "prep_queue.log")

SERVICES = ["abyss", "turboviplay", "mixdrop", "ddownload", "filepress", "gofile", "pixeldrain", "upfiles"]

MAX_EPISODES = 50
DEFAULT_QUEUE_LIMIT = 30

TYPE_FILTERS = {
    "tv": ["TV"],
    "ona": ["ONA"],
    "special": ["Special"],
    "all": ["TV", "ONA", "Special"]
}

# Note: API only has /top-airing endpoint. Filter by showType from tvInfo.

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")
    with open(LOG_FILE, "a") as f:
        f.write(f"[{ts}] {msg}\n")

def load_master():
    if os.path.exists(MASTER_FILE):
        with open(MASTER_FILE) as f:
            return json.load(f)
    return {}

def save_master(data):
    with open(MASTER_FILE, "w") as f:
        json.dump(data, f, indent=2)

def load_in_progress():
    if os.path.exists(IN_PROGRESS_FILE):
        with open(IN_PROGRESS_FILE) as f:
            return set(line.strip() for line in f if line.strip())
    return set()

def add_to_in_progress(anime_id):
    with open(IN_PROGRESS_FILE, "a") as f:
        f.write(f"{anime_id}\n")

def remove_from_in_progress(anime_id):
    if not os.path.exists(IN_PROGRESS_FILE):
        return
    with open(IN_PROGRESS_FILE) as f:
        lines = [l.strip() for l in f if l.strip() and l.strip() != anime_id]
    with open(IN_PROGRESS_FILE, "w") as f:
        f.write("\n".join(lines) + "\n")

def get_existing_queue():
    existing = {}
    if os.path.exists(QUEUE_FILE):
        with open(QUEUE_FILE) as f:
            for line in f:
                parts = line.strip().split("|")
                if len(parts) >= 3:
                    existing[parts[0]] = {
                        "anime_id": parts[0],
                        "start_ep": int(parts[1]),
                        "total_eps": int(parts[2])
                    }
    return existing

def get_anime_list(endpoint="top-airing", page=1, limit=20):
    try:
        r = requests.get(f"{ANIWATCH_API}/{endpoint}", params={"page": page}, timeout=60)
        if r.status_code == 200:
            data = r.json()
            # New API format: {"success": true, "anime": [...]}
            # Old API format: {"results": {"data": [...]}}
            if "anime" in data:
                return data.get("anime", [])
            return data.get("results", {}).get("data", [])
    except Exception as e:
        log(f"Error fetching page {page}: {e}")
    return []

def get_episode_count(anime_id):
    try:
        # New API: /info/{slug} returns recent_episodes
        r = requests.get(f"{ANIWATCH_API}/info/{anime_id}", timeout=60)
        if r.status_code == 200:
            data = r.json()
            # New API returns recent_episodes array
            recent = data.get("recent_episodes", [])
            return len(recent), recent
        # Fallback to old endpoint
        r = requests.get(f"{ANIWATCH_API}/episodes/{anime_id}", params={"page": 1}, timeout=30)
        if r.status_code == 200:
            data = r.json()
            result = data.get("results", {})
            return result.get("totalEpisodes", 0), result.get("episodes", [])
    except Exception as e:
        log(f"Error getting episodes for {anime_id}: {e}")
    return 0, []

def check_already_done(anime_id, total_eps, master):
    if anime_id not in master:
        return False
    entry = master[anime_id]
    processed_eps = entry.get("processed_eps", [])
    if isinstance(processed_eps, list) and len(processed_eps) < total_eps:
        return False
    return True

def check_new_episodes(anime_id, total_eps, master):
    if anime_id not in master:
        return False
    entry = master[anime_id]
    old_total = entry.get("total_eps", 0)
    return total_eps > old_total

def get_next_unprocessed_ep(anime_id, total_eps, master):
    if anime_id not in master:
        return 1
    entry = master[anime_id]
    processed_eps = entry.get("processed_eps", [])
    if not isinstance(processed_eps, list):
        processed_eps = []
    for ep in range(1, total_eps + 1):
        if ep not in processed_eps:
            return ep
    return None

VALID_ENDPOINTS = ["top-airing", "most-popular", "most-favorite", "movie", "tv", "ova", "ona", "special", "recently-added", "recently-updated", "top-upcoming", "completed", "recently-added"]

def main():
    parser = argparse.ArgumentParser(description="Prepare anime processing queue")
    parser.add_argument("--endpoint", "-e", 
                       choices=VALID_ENDPOINTS,
                       help=f"API endpoint to fetch from: {', '.join(VALID_ENDPOINTS)}")
    parser.add_argument("--type", "-t", default="tv", 
                       choices=["tv", "ona", "special", "all"],
                       help="Filter by showType: tv|ona|special|all (default: tv) [for top-airing only]")
    parser.add_argument("--force", "-f", action="store_true",
                       help="Force full refetch (ignore smart mode)")
    parser.add_argument("--limit", "-l", type=int, default=DEFAULT_QUEUE_LIMIT,
                       help=f"Maximum anime in queue (default: {DEFAULT_QUEUE_LIMIT})")
    args = parser.parse_args()
    
    endpoint = args.endpoint if args.endpoint else "top-airing"
    
    log("=" * 50)
    log("🎯 PREP QUEUE - Starting")
    log(f"📡 Endpoint: {endpoint}")
    log(f"   (Full URL: {ANIWATCH_API}/{endpoint})")
    
    os.makedirs(TRACKING_DIR, exist_ok=True)
    os.makedirs(os.path.join(TRACKING_DIR, "processed"), exist_ok=True)
    
    master = load_master()
    in_progress = load_in_progress()
    existing_queue = get_existing_queue()
    
    log(f"📊 Existing queue: {len(existing_queue)} anime")
    log(f"📊 In progress: {len(in_progress)} anime")
    
    anime_list = []
    log(f"📡 Fetching anime from {endpoint}...")
    for page in range(1, 4):
        log(f"  Page {page}...")
        items = get_anime_list(endpoint, page)
        anime_list.extend(items)
        time.sleep(0.5)
    
    log(f"📋 Fetched {len(anime_list)} anime")
    
    # Note: Type filtering is now handled by endpoint selection
    # Only apply showType filter for top-airing endpoint
    
    queue = []
    new_additions = 0
    
    for anime in anime_list:
        anime_id = anime.get("id")
        title = anime.get("title", "Unknown")
        
        if anime_id in in_progress:
            log(f"  🔄 In progress: {title}")
            continue
        
        if anime_id in existing_queue:
            log(f"  ⏭️  Already queued: {title}")
            queue.append(existing_queue[anime_id])
            continue
        
        total_eps, _ = get_episode_count(anime_id)
        
        if total_eps == 0:
            log(f"  ⏭️  Skipping (no eps): {title}")
            continue
        
        if total_eps > MAX_EPISODES:
            log(f"  ⏭️  Skipping (too long {total_eps}eps): {title[:40]}")
            continue
        
        if check_already_done(anime_id, total_eps, master):
            log(f"  ✅ Already done: {title}")
            continue
        
        has_new_eps = check_new_episodes(anime_id, total_eps, master)
        if anime_id in master and not has_new_eps:
            log(f"  ⏭️  Skipping (already processed): {title}")
            continue
        
        start_ep = get_next_unprocessed_ep(anime_id, total_eps, master)
        
        if start_ep is None:
            continue
        
        entry = {
            "anime_id": anime_id,
            "title": title,
            "total_eps": total_eps,
            "start_ep": start_ep,
            "type": endpoint
        }
        queue.append(entry)
        new_additions += 1
        
        log(f"  📝 Added: {title} ({start_ep}-{total_eps}) [{endpoint}]")
        time.sleep(0.3)
    
    queue.sort(key=lambda x: x["total_eps"])
    queue = queue[:args.limit]
    
    with open(QUEUE_FILE, "w") as f:
        for item in queue:
            f.write(f"{item['anime_id']}|{item['start_ep']}|{item['total_eps']}\n")
    
    log(f"✅ Queue saved: {len(queue)} anime ({new_additions} new)")
    log(f"📄 Queue file: {QUEUE_FILE}")
    
    log("\n📋 TOP 10 QUEUE:")
    for i, item in enumerate(queue[:10], 1):
        title = item.get("title", item.get("anime_id", ""))[:30]
        log(f"  {i}. {title} | Eps {item['start_ep']}-{item['total_eps']} [{item.get('type','TV')}]")

if __name__ == "__main__":
    main()
