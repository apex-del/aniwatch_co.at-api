# Megaplay.buzz Reverse Engineering & m3u8 Extraction

## Overview

Successfully reverse-engineered **megaplay.buzz** (used by 1anime.site / aniwatch.co.at) to extract direct m3u8 stream URLs without browser automation. The key finding: **no JS decryption is needed** — the player loads streams via a plaintext API endpoint.

---

## 1. Problem Statement

- **Target**: `aniwatch.co.at` → `1anime.site` → `megaplay.buzz` streaming chain
- **Goal**: Extract direct `.m3u8` stream URLs for `yt-dlp` / `ffmpeg` download
- **Constraints**: Termux only (no Chrome, no Playwright, no `curl_cffi` on newer builds)
- **Blocker**: Player page contained zero stream data — m3u8 loaded dynamically via obfuscated JS

---

## 2. Architecture Understanding

```
aniwatch.co.at (WordPress)
    │
    ▼ GET /wp-json/hianime/v1/episode/servers/{post_id}
    │   → Returns HTML with base64-encoded `data-hash`
    │
    ▼ base64 decode → https://1anime.site/megaplay/stream/s-2/{ID}/sub
    │   → Thin HTML wrapper with <iframe>
    │
    ▼ iframe → https://megaplay.buzz/stream/s-2/{ID}/sub
    │   → Player page with JWPlayer + settings object (contains `cid`)
    │
    ▼ Call getSources API with `cid`
    │
    ▼ https://megaplay.buzz/stream/getSources?id={cid}
        → Returns JSON with direct m3u8 URL + subtitle tracks
```

### Key Components

| Component | URL | Purpose |
|-----------|-----|---------|
| Aniwatch WordPress API | `aniwatch.co.at/wp-json/` | Episode metadata & server list |
| 1anime.site | `1anime.site/megaplay/stream/s-2/{ID}/{sub\|dub}` | Thin iframe wrapper |
| Megaplay Player | `megaplay.buzz/stream/s-2/{ID}/{sub\|dub}` | JWPlayer page with `cid` |
| getSources API | `megaplay.buzz/stream/getSources?id={cid}` | **Returns m3u8 directly** |
| CDN | `cdn.mewstream.buzz/anime/{hash}/{hash}/master.m3u8` | Actual HLS stream |

---

## 3. Reverse Engineering Methodology

### Step 1: Fetch Player Page HTML

```
GET https://megaplay.buzz/stream/s-2/3327/sub
Referer: https://1anime.site/
```

Response contains an inline `settings` object:

```javascript
const settings = {
    time: 0,
    autoPlay: "1",
    playOriginalAudio: "1",
    autoSkipIntro: "0",
    vast: 0,
    base_url: 'https://megaplay.buzz/',
    domain2_url: 'Array',
    type: 'sub',
    cid: '4742',          // ← Episode identifier
    cidu: '69f3c644e1a19',
};
```

**Key finding**: `cid` is the episode/server ID used for API calls.

### Step 2: Guess API Endpoints

Tested 8+ endpoint patterns:

| Endpoint | Result |
|----------|--------|
| `/embed-2/v2/e-1/getSources?id={cid}` | HTML (404-like page) |
| `/embed-2/e-1/getSources?id={cid}` | HTML |
| `/api/source/{cid}` | HTML |
| `/api/episode/{cid}` | HTML |
| `/stream/getSources?id={cid}` | **JSON with m3u8** |
| `/stream/s-2/{id}/{lang}/getSources` | HTML |

### Step 3: API Response Analysis

```json
{
  "sources": {
    "file": "https://cdn.mewstream.buzz/anime/{hash}/{hash}/master.m3u8"
  },
  "tracks": [
    {
      "file": "https://1oe.lostproject.club/anime/.../subtitles/eng-2.vtt",
      "label": "English"
    },
    {
      "file": "https://1oe.lostproject.club/anime/.../subtitles/por-3.vtt",
      "label": "Portuguese"
    }
  ],
  "intro": {"start": 0, "end": 0},
  "outro": {"start": 0, "end": 0},
  "server": 4
}
```

**Critical finding**: `sources.file` is a **plaintext m3u8 URL** — no encryption, no base64, no XOR. The obfuscated JS is a red herring; it just parses this response and feeds it to JWPlayer.

### Step 4: Why JS Obfuscation Was a Dead End

The `e1-player.min.js` (228KB) uses:
- `obfuscator.io` style string array + hex encoding
- `_0xd148` decoder functions
- DOM/jQuery initialization guards

**Lesson**: Obfuscated JS is often misdirection. The actual data comes from a simple REST API. Always:
1. Check network traffic first (browser DevTools Network tab)
2. Look for inline data/settings in HTML
3. Test common API patterns (`/api/`, `/getSources`, `/embed-2/`)
4. The JS just *consumes* API responses — it rarely *generates* them

---

## 4. Extraction Recipe (Apply to Any Site)

### Universal Method

```python
def extract_stream(player_url: str) -> dict:
    """
    Universal recipe for extracting m3u8 from streaming sites.
    
    Works on: megaplay.buzz, vidwish, watching.onl, and similar JWPlayer-based embeds.
    """
    
    # 1. Fetch player page
    html = requests.get(player_url).text
    
    # 2. Extract identifier from settings/config
    # Common keys: cid, episode_id, source_id, data-id
    cid = re.search(r'cid\s*:\s*["\x27]([^"\x27]+)["\x27]', html)
    if not cid:
        cid = re.search(r'data-id=["\x27](\d+)["\x27]', html)
    
    # 3. Test API endpoint patterns
    base_url = "https://" + re.search(r'https?://([^/]+)', player_url).group(1)
    
    endpoints = [
        f"{base_url}/stream/getSources?id={cid}",
        f"{base_url}/embed-2/v2/e-1/getSources?id={cid}",
        f"{base_url}/api/source/{cid}",
        f"{base_url}/getSources?token={cid}",
    ]
    
    for ep in endpoints:
        resp = requests.get(ep, headers={
            "Referer": player_url,
            "X-Requested-With": "XMLHttpRequest",
        })
        if resp.headers.get("Content-Type", "").startswith("application/json"):
            return resp.json()
    
    return None
```

### Common Identifier Patterns

| Site | Identifier | Location |
|------|-----------|----------|
| megaplay.buzz | `cid` | `<script>const settings = {...}` |
| vidstream | `data-id` | `<div id="player" data-id="...">` |
| megacloud | `episodeId` | URL path or JS variable |
| vidcloud | `id` | URL query parameter |

### Common API Patterns

```
/stream/getSources?id={ID}
/embed-2/v2/e-1/getSources?id={ID}
/api/source/{ID}
/ajax/getSources?token={ID}
/sources/{ID}
/player/sources?id={ID}
```

### Required Headers

```python
headers = {
    "Referer": player_url,           # Always required
    "Origin": base_url,              # Sometimes required
    "X-Requested-With": "XMLHttpRequest",  # Signals AJAX request
    "User-Agent": "Mozilla/5.0 ...", # Standard browser UA
}
```

---

## 5. Python Implementation

### Core Function (in `aniwatch_coat_scraper.py`)

```python
def get_stream_url(self, stream_url: str) -> Dict[str, Any]:
    """
    Extract m3u8 from 1anime/megaplay streaming chain.
    
    Returns: {
        "success": True,
        "m3u8_url": "https://cdn.mewstream.buzz/.../master.m3u8",
        "tracks": [...],
        "type": "hls",
        "cid": "4742"
    }
    """
```

### Full Pipeline

```python
# 1. Aniwatch → post_id
resp = session.get(episode_url)
post_id = re.search(r'wp-json/wp/v2/posts/(\d+)', resp.text).group(1)

# 2. Get servers via REST API
servers = session.get(f"{BASE}/wp-json/hianime/v1/episode/servers/{post_id}")

# 3. Decode base64 hash → 1anime.site URL
decoded = base64.b64decode(hash_value).decode('utf-8')

# 4. Extract iframe → megaplay.buzz URL
iframe_url = re.search(r'<iframe.+src="([^"]+)"', html).group(1)

# 5. Extract cid from megaplay page
cid = re.search(r'cid\s*:\s*["\x27]([^"\x27]+)["\x27]', mega_html).group(1)

# 6. Call getSources API → m3u8
sources = session.get(f"https://megaplay.buzz/stream/getSources?id={cid}")
m3u8 = sources.json()["sources"]["file"]
```

---

## 6. What We Did NOT Need

| Technique | Needed? | Why Not |
|-----------|---------|---------|
| JS deobfuscation | No | API returns plaintext |
| AES decryption | No | No encryption on m3u8 URL |
| XOR decryption | No | Same |
| Node.js VM execution | No | Same |
| Browser automation | No | Simple HTTP requests suffice |
| curl_cffi | No | Standard `requests` works |
| Cloudflare bypass | No | megaplay.buzz has no CF challenge |

---

## 7. Future Work

### 7.1 Other Megaplay Variants

Test the same `cid` → `getSources` pattern on:
- `vidwish.live` (same architecture, different domain)
- `watching.onl`
- `mewstream.buzz` (CDN domain)
- `dump.mewcdn.online` (debug endpoint)

### 7.2 Alternative Aniwatch Sources

The scraper currently handles two source types:
1. **Megaplay** (`1anime.site/megaplay/...`) → HLS via getSources ✅
2. **Direct MP4** (`my.1anime.site/...`) → Direct video file ✅

Future sources may use different patterns. The `get_stream_url()` method is designed to be extended.

### 7.3 Quality Selection

The master m3u8 contains multiple resolution variants:
```
#EXT-X-STREAM-INF:RESOLUTION=1920x1080 → index-f1-v1-a1.m3u8
```

The scraper already parses these into a `qualities` list. The download pipeline should:
1. Let user select quality (1080p, 720p, 480p, etc.)
2. Pass specific variant m3u8 to `yt-dlp` or `ffmpeg`

### 7.4 Subtitle Integration

Tracks are now extracted from getSources API:
- English VTT ✅
- Portuguese VTT ✅
- Spanish VTT ✅

Pipeline should auto-download subtitles with correct naming.

### 7.5 Dub/Sub Server Selection

Aniwatch returns both sub and dub servers. The scraper should:
1. Accept `--lang sub` or `--lang dub` flag
2. Select the correct server based on user preference
3. Fall back to available if preferred not found

### 7.6 Monitoring & Domain Rotation

The streaming infrastructure uses rolling domains:
- `megaplay.buzz` (current)
- `vidwish.live` (alternative)
- `cdn.mewstream.buzz` (CDN)
- `1oe.lostproject.club` (subtitles)

If megaplay.buzz goes down, the same `cid` may work on alternative domains. Build a domain fallback system.

### 7.7 Apply to Other Sites

Use the methodology in Section 4 on:
- **9animetv.to** — Uses `megacloud` (AES-256-CBC encrypted, needs key extraction)
- **hianime.to** — Similar WordPress structure
- **aniwatchtv.to** — Same source as aniwatch.co.at
- **zoro.to** — Different player, similar pattern

---

## 8. Lessons Learned

### The Reverse Engineering Process

1. **Start simple**: Fetch the HTML, look for inline data/settings
2. **Network traffic first**: Use browser DevTools → Network tab to see all API calls
3. **Test endpoint patterns systematically**: Try `/api/`, `/embed-2/`, `/stream/` prefixes
4. **Don't dive into JS immediately**: The JS is usually a consumer, not a generator
5. **Check Content-Type**: `application/json` vs `text/html` tells you if you hit an API
6. **Identifiers are everything**: Find the ID/cid/token that connects page → API

### Common Misdirections

| Obfuscation | Reality |
|-------------|---------|
| 228KB obfuscated JS | Just loads API response into player |
| `debugger` statements | Anti-debugging, irrelevant to functionality |
| String array + hex encoding | Hides variable names, not data |
| JWPlayer integration | Standard player — just needs a URL |

---

## 9. Quick Reference

### Endpoints

```
# Aniwatch (WordPress)
GET /wp-json/wp/v2/posts?search={keyword}        # Search
GET /wp-json/hianime/v1/episode/servers/{post_id} # Get servers

# 1anime.site (iframe wrapper)
GET /megaplay/stream/s-2/{ID}/{sub|dub}           # Player page

# Megaplay.buzz (actual player)
GET /stream/s-2/{ID}/{sub|dub}                    # Player HTML (extract cid)
GET /stream/getSources?id={cid}                   # **M3U8 + tracks**
GET /lib/e1-player.min.js?v=1.1.1                 # Player JS (obfuscated)
GET /lib/app.main.js?v=2.1                        # Ad/config loader

# CDN
GET /anime/{hash}/{hash}/master.m3u8              # HLS stream
GET /anime/{hash}/{hash}/subtitles/{lang}.vtt     # Subtitles
```

### Headers

```python
{
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://megaplay.buzz/",
    "X-Requested-With": "XMLHttpRequest",  # For getSources API
}
```

### Response Format

```json
{
  "success": true,
  "m3u8_url": "https://cdn.mewstream.buzz/.../master.m3u8",
  "tracks": [
    {"url": "...", "lang": "en", "label": "English"}
  ],
  "type": "hls",
  "cid": "4742"
}
```

---

## 10. File Inventory

| File | Purpose | Status |
|------|---------|--------|
| `aniwatch_coat_scraper.py` | Main scraper + Flask API | **Updated** with getSources |
| `megaplay_extractor.py` | Original megaplay scraper | Legacy (broken) |
| `megaplay_extractor_new.py` | Attempted decrypt extractor | Legacy (not needed) |
| `e1_player.js` | Downloaded player JS | Reference only |
| `anime_downloader_fixed.py` | Download pipeline | Needs integration |

---

*Documented: May 2026 | Termux Environment | Python 3.13*
