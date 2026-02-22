#!/usr/bin/env python3
"""
fetch_favorites.py
------------------
Fetches your saved/favorite songs from:
  - ultimateguitar.com  (English)
  - tab4u.com           (Hebrew)

Then generates random_song.html — open it in any browser.

Requirements:
    pip install requests beautifulsoup4 browser-cookie3

Usage:
    python fetch_favorites.py                   # Chrome (default)
    python fetch_favorites.py --browser firefox
    python fetch_favorites.py --debug           # dump raw page data for inspection

If cookie extraction fails, see the MANUAL FALLBACK section below.
"""

import argparse
import json
import os
import re
import sys
import urllib.parse

import requests
from bs4 import BeautifulSoup

try:
    import browser_cookie3
    HAS_BROWSER_COOKIE3 = True
except ImportError:
    HAS_BROWSER_COOKIE3 = False

try:
    import rookiepy
    HAS_ROOKIEPY = True
except ImportError:
    HAS_ROOKIEPY = False

# ---------------------------------------------------------------------------
# Cookie helpers
# ---------------------------------------------------------------------------

def _cj_to_dict(cj) -> dict:
    """Convert a cookiejar to a latin-1-safe dict (HTTP header requirement)."""
    safe = {}
    for cookie in cj:
        val = cookie.value or ""
        try:
            val.encode("latin-1")
        except (UnicodeEncodeError, UnicodeDecodeError):
            val = urllib.parse.quote(val, safe="")
        safe[cookie.name] = val
    return safe


def get_cookies(domain: str, browser: str) -> dict:
    """
    Return cookies for *domain* as a plain dict with safe (ASCII) values.
    For Chrome, tries rookiepy first (handles Chrome 127+ encryption),
    then falls back to browser_cookie3.
    """
    if browser == "chrome" and HAS_ROOKIEPY:
        # rookiepy correctly decrypts Chrome 127+ App-Bound Encrypted cookies.
        # It returns a list of dicts, not a CookieJar.
        cookies_list = rookiepy.chrome(domains=[domain])
        safe = {}
        for c in cookies_list:
            name = c.get("name", "")
            val  = c.get("value", "") or ""
            try:
                val.encode("latin-1")
            except (UnicodeEncodeError, UnicodeDecodeError):
                val = urllib.parse.quote(val, safe="")
            if name:
                safe[name] = val
        return safe

    if not HAS_BROWSER_COOKIE3:
        print("ERROR: neither rookiepy nor browser-cookie3 is installed.")
        print("  Run:  pip install rookiepy")
        sys.exit(1)

    fn = getattr(browser_cookie3, browser, None)
    if fn is None:
        print(f"ERROR: unsupported browser '{browser}'")
        sys.exit(1)
    cj = fn(domain_name=domain)
    safe = _cj_to_dict(cj)
    return safe


# ---------------------------------------------------------------------------
# Ultimate Guitar
# ---------------------------------------------------------------------------

def fetch_ug_favorites(browser: str, debug: bool) -> list[dict]:
    """
    UG is a Next.js app. It embeds all SSR data in <script id="__NEXT_DATA__">.
    The favorites list lives at:
        props → pageProps → store → page → data → tabs[]
    Each tab has: song_name, artist_name, tab_url, type
    """
    print("→ Fetching Ultimate Guitar favorites …")
    cookies = get_cookies("ultimate-guitar.com", browser)
    session = requests.Session()
    session.cookies.update(cookies)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    # /user/mytabs and /user/favorites both surface saved tabs
    resp = None
    for url in [
        "https://tabs.ultimate-guitar.com/user/favorites",
        "https://tabs.ultimate-guitar.com/user/mytabs",
    ]:
        r = session.get(url, headers=headers, timeout=15, allow_redirects=True)
        # If we ended up on a login page, skip
        if r.status_code == 200 and "login" not in r.url.lower():
            resp = r
            break

    if resp is None:
        print(f"  ✗ Ultimate Guitar blocked the request (status: {r.status_code}).")
        print("    UG uses Cloudflare bot protection that blocks automated fetching.")
        print()
        print("    ONE-TIME MANUAL STEP:")
        print("    1. Open Chrome and log into ultimateguitar.com")
        print("    2. Navigate to your saved/favourite tabs page")
        print("       (Profile menu → My Tabs, or Favourites)")
        print("    3. Press Cmd+S → save as 'ug_favorites.html' in:")
        print(f"       {os.path.dirname(os.path.abspath(__file__))}")
        print("    4. Re-run this script — it will read that file automatically.")
        print()

        # Try reading the manually saved file
        manual_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ug_favorites.html")
        if os.path.exists(manual_path):
            print(f"    Found ug_favorites.html — using it.")
            resp = type("R", (), {"text": open(manual_path, encoding="utf-8").read(), "url": "file"})()
        else:
            return []

    soup = BeautifulSoup(resp.text, "html.parser")
    script_tag = soup.find("script", id="__NEXT_DATA__")

    songs = []

    if script_tag:
        # Next.js SSR path: data embedded in __NEXT_DATA__
        data = json.loads(script_tag.string)

        if debug:
            with open("ug_debug.json", "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print("    Saved parsed JSON → ug_debug.json")

        def _find_tabs(d):
            try:
                return d["props"]["pageProps"]["store"]["page"]["data"]["tabs"]
            except (KeyError, TypeError):
                pass
            try:
                return d["props"]["pageProps"]["data"]["tabs"]
            except (KeyError, TypeError):
                pass
            return None

        tabs = _find_tabs(data)
        if tabs is not None:
            for tab in tabs:
                song_name = tab.get("song_name") or tab.get("name") or "Unknown"
                artist    = tab.get("artist_name") or tab.get("artist") or "Unknown"
                tab_url   = tab.get("tab_url") or tab.get("url") or ""
                if tab_url and not tab_url.startswith("http"):
                    tab_url = "https://tabs.ultimate-guitar.com" + tab_url
                if not tab_url:
                    continue
                songs.append({
                    "title":  song_name,
                    "artist": artist,
                    "url":    tab_url,
                    "source": "Ultimate Guitar",
                    "lang":   "en",
                })

    if not songs:
        # React SPA path: data is rendered into <a href> links in the DOM.
        # URL pattern: /tab/{artist-slug}/{title-type-id}
        # e.g. /tab/elton-john/sacrifice-chords-978610
        tab_urls = re.findall(
            r'href="(https://tabs\.ultimate-guitar\.com/tab/[^"]+)"',
            resp.text
        )
        seen = set()
        for url in tab_urls:
            if url in seen:
                continue
            seen.add(url)
            # Parse artist and title from slug
            path = url.split("/tab/", 1)[1]          # e.g. "elton-john/sacrifice-chords-978610"
            parts = path.split("/", 1)
            artist_slug = parts[0]
            title_slug  = parts[1] if len(parts) > 1 else ""
            # Strip trailing -type-digits (e.g. "-chords-978610")
            title_parts = title_slug.split("-")
            if len(title_parts) >= 2 and title_parts[-1].isdigit():
                title_parts = title_parts[:-2]       # drop type + id
            artist = artist_slug.replace("-", " ").title()
            title  = " ".join(title_parts).title()
            songs.append({
                "title":  title,
                "artist": artist,
                "url":    url,
                "source": "Ultimate Guitar",
                "lang":   "en",
            })

    print(f"  ✓ Found {len(songs)} song(s)")
    return songs


# ---------------------------------------------------------------------------
# Tab4u
# ---------------------------------------------------------------------------

def _parse_tab4u_song_url(href: str) -> tuple[str, str]:
    """
    Extract artist and title from a tab4u song URL.
    Pattern: /tabs/songs/{ID}_{Artist}_-_{Song}.html
    Example: /tabs/songs/74165_Foo_Fighters_-_My_Hero.html
             → ("Foo Fighters", "My Hero")
    Works for both Latin and Hebrew (URL-encoded) filenames.
    """
    try:
        filename = os.path.basename(href.split("?")[0])       # e.g. "74165_Foo_Fighters_-_My_Hero.html"
        filename = urllib.parse.unquote(filename)              # decode %D7%A9... → Hebrew chars
        filename = filename.removesuffix(".html")

        if "_-_" in filename:
            left, right = filename.split("_-_", 1)
            artist = re.sub(r"^\d+_", "", left)               # strip leading numeric ID
            artist = artist.replace("_", " ").strip()
            title  = right.replace("_", " ").strip()
            return artist, title
        else:
            name = re.sub(r"^\d+_", "", filename).replace("_", " ").strip()
            return "Unknown", name
    except Exception:
        return "Unknown", "Unknown"


def fetch_tab4u_favorites(browser: str, debug: bool) -> list[dict]:
    """
    tab4u.com loads the user's saved songs via an AJAX PHP endpoint:
        /specLoaderSongs.php?id={user_id}
    We first load the chordsbook page to extract the user ID, then call
    the endpoint directly.
    """
    print("→ Fetching Tab4u favorites …")

    script_dir = os.path.dirname(os.path.abspath(__file__))
    manual_path = os.path.join(script_dir, "tab4u_mysongs.html")

    # Try the manual saved file first (most reliable — no session issues)
    if os.path.exists(manual_path):
        print(f"    Found tab4u_mysongs.html — using it.")
        raw = open(manual_path, encoding="utf-8").read()
    else:
        cookies = get_cookies("tab4u.com", browser)
        session = requests.Session()
        session.cookies.update(cookies)

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "he-IL,he;q=0.9,en;q=0.8",
        }

        # Call the "My Songs" AJAX endpoint directly — no page load needed.
        # Discovered from tab4u's main.js: getMySongs.php?lan=0&otherUId=0&aID=0
        # otherUId=0 means "my own songs" (uses the session cookie for auth).
        # Response uses "`TOPALB`" and "`TOPEND`" as section delimiters.
        referer = "https://www.tab4u.com/articles/chordsbook?mySongs=2"
        ajax_url = "https://www.tab4u.com/getMySongs.php?lan=0&otherUId=0&aID=0"
        ajax_headers = {**headers, "X-Requested-With": "XMLHttpRequest", "Referer": referer}
        ajax_resp = session.get(ajax_url, headers=ajax_headers, timeout=15)
        ajax_resp.encoding = "utf-8"
        raw = ajax_resp.text

        if debug:
            with open("tab4u_ajax_debug.html", "w", encoding="utf-8") as f:
                f.write(raw)
            print("    Saved getMySongs response → tab4u_ajax_debug.html")

        # Detect login-wall response (short HTML with "login" prompt)
        login_required = (
            ajax_resp.status_code != 200
            or len(raw.strip()) < 200
            or "firstLoginBut" in raw
            or "להתחבר" in raw
        )
        if login_required:
            print("  ✗ Tab4u session expired or not logged in.")
            print()
            print("    ONE-TIME MANUAL STEP:")
            print("    1. Open Chrome and log into tab4u.com")
            print("    2. Navigate to this URL (while logged in):")
            print("       https://www.tab4u.com/getMySongs.php?lan=0&otherUId=0&aID=0")
            print("    3. Press Cmd+S → save as 'tab4u_mysongs.html' in:")
            print(f"       {script_dir}")
            print("    4. Re-run this script — it will read that file automatically.")
            print()
            return []

    # Parse the delimited response to get the songs HTML section
    if "`TOPALB`" in raw:
        raw = raw.split("`TOPALB`", 1)[1]
    if "`TOPEND`" in raw:
        raw = raw.split("`TOPEND`", 1)[1]

    raw_song_paths = re.findall(r"/tabs/songs/[^\s\"'<>\\]+\.html", raw)

    seen = set()
    songs = []
    for path in raw_song_paths:
        if path in seen:
            continue
        seen.add(path)

        full_url = f"https://www.tab4u.com{path}"
        artist, title = _parse_tab4u_song_url(path)

        songs.append({
            "title":  title,
            "artist": artist,
            "url":    full_url,
            "source": "Tab4u",
            "lang":   "he",
        })

    print(f"  ✓ Found {len(songs)} song(s)")
    return songs


# ---------------------------------------------------------------------------
# HTML generator
# ---------------------------------------------------------------------------

def generate_html(songs: list[dict]) -> str:
    songs_json = json.dumps(songs, ensure_ascii=False, indent=2)
    count = len(songs)

    return f"""<!DOCTYPE html>
<html lang="he" dir="auto">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Random Song Picker 🎸</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

    body {{
      height: 100dvh;
      display: flex;
      background: #0f0e17;
      color: #fffffe;
      font-family: system-ui, -apple-system, sans-serif;
    }}

    #layout {{
      display: flex;
      flex: 1;
      height: 100dvh;
    }}

    #empty {{ flex: 1; }}

    /* ── Middle panel: picker ── */
    #main {{
      flex: 1;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 1.75rem;
      padding: 2rem 1.5rem;
      border-right: 1px solid #2a2a4a;
    }}

    h1 {{
      font-size: 1.1rem;
      color: #a7a9be;
      letter-spacing: 0.1em;
      text-transform: uppercase;
      font-weight: 500;
      text-align: center;
    }}

    #card {{
      background: #1b1b2e;
      border: 1px solid #2a2a4a;
      border-radius: 16px;
      padding: 2rem 1.5rem;
      width: 100%;
      text-align: center;
      min-height: 180px;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 0.85rem;
      transition: opacity 0.25s;
    }}

    #card.fade {{ opacity: 0; }}

    #hint {{ color: #4a4a6a; font-size: 0.85rem; }}

    #badge {{
      font-size: 0.65rem;
      font-weight: 700;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      padding: 0.25rem 0.8rem;
      border-radius: 999px;
      background: #2a2a4a;
      color: #a7a9be;
      display: none;
    }}

    #artist {{ font-size: 0.85rem; color: #a7a9be; display: none; }}

    #title {{
      font-size: 1.6rem;
      font-weight: 800;
      line-height: 1.2;
      color: #fffffe;
      display: none;
    }}

    .buttons {{
      display: flex;
      gap: 0.75rem;
      flex-wrap: wrap;
      justify-content: center;
    }}

    button {{
      padding: 0.65rem 1.4rem;
      border-radius: 10px;
      border: none;
      cursor: pointer;
      font-size: 0.9rem;
      font-weight: 700;
      letter-spacing: 0.03em;
      transition: filter 0.15s, transform 0.1s;
    }}

    button:hover  {{ filter: brightness(1.15); }}
    button:active {{ transform: scale(0.97); }}

    #btn-random {{ background: #6246ea; color: #fffffe; }}
    #btn-open   {{ background: #e45858; color: #fffffe; display: none; }}

    #counter {{ font-size: 0.72rem; color: #3a3a5a; margin-top: -0.75rem; }}

    /* ── Right panel: song list ── */
    #browser {{
      flex: 1;
      display: flex;
      flex-direction: column;
      gap: 0.6rem;
      padding: 1.25rem 0.9rem;
    }}

    #search {{
      width: 100%;
      padding: 0.5rem 0.8rem;
      border-radius: 8px;
      border: 1px solid #2a2a4a;
      background: #1b1b2e;
      color: #fffffe;
      font-size: 0.85rem;
      outline: none;
      flex-shrink: 0;
    }}

    #search:focus {{ border-color: #6246ea; }}

    #controls {{
      display: flex;
      gap: 0.4rem;
      flex-shrink: 0;
    }}

    #controls #search {{ flex: 1; }}

    #sort {{
      padding: 0.5rem 0.5rem;
      border-radius: 8px;
      border: 1px solid #2a2a4a;
      background: #1b1b2e;
      color: #a7a9be;
      font-size: 0.8rem;
      outline: none;
      cursor: pointer;
      flex-shrink: 0;
    }}

    #sort:focus {{ border-color: #6246ea; }}

    #song-list {{
      flex: 1;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
      gap: 0.25rem;
      scrollbar-width: thin;
      scrollbar-color: #2a2a4a transparent;
    }}

    .song-row {{
      display: flex;
      align-items: center;
      gap: 0.5rem;
      padding: 0.45rem 0.7rem;
      border-radius: 8px;
      cursor: pointer;
      background: transparent;
      border: 1px solid transparent;
      transition: border-color 0.12s, background 0.12s;
      text-align: start;
      width: 100%;
    }}

    .song-row:hover {{ border-color: #6246ea; background: #1b1b2e; }}

    .song-row .flag {{ font-size: 0.85rem; flex-shrink: 0; }}

    .song-row .info {{ display: flex; flex-direction: column; min-width: 0; }}

    .song-row .s-title {{
      font-size: 0.82rem;
      font-weight: 600;
      color: #fffffe;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}

    .song-row .s-artist {{
      font-size: 0.68rem;
      color: #6a6a8a;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}

    #list-count {{
      font-size: 0.68rem;
      color: #3a3a5a;
      text-align: center;
      flex-shrink: 0;
    }}
  </style>
</head>
<body>
  <div id="layout">
    <div id="empty"></div>
    <div id="main">
      <h1>🎸 Random Song Picker</h1>

      <div id="card">
        <p id="hint">Pick random or choose from the list</p>
        <span id="badge"></span>
        <div id="artist"></div>
        <div id="title"></div>
      </div>

      <div class="buttons">
        <button id="btn-random" onclick="pickRandom()">🎲 Pick Random</button>
        <button id="btn-open"   onclick="openSong()">Open Tab →</button>
      </div>

      <p id="counter"></p>
    </div>

    <div id="browser">
      <div id="controls">
        <input id="search" type="search" placeholder="Filter…" oninput="renderFiltered()" />
        <select id="sort" onchange="renderFiltered()">
          <option value="title">Title</option>
          <option value="artist">Artist</option>
          <option value="source">Source</option>
          <option value="random">Random</option>
        </select>
      </div>
      <div id="song-list"></div>
      <p id="list-count"></p>
    </div>
  </div>

  <script>
    const songs = {songs_json};
    let currentUrl = null;
    let pickCount  = 0;

    const collator = new Intl.Collator(undefined, {{ sensitivity: 'base' }});

    function showSong(song) {{
      const card = document.getElementById('card');
      card.classList.add('fade');
      setTimeout(() => {{
        currentUrl = song.url;
        pickCount++;

        document.getElementById('hint').style.display = 'none';

        const badge   = document.getElementById('badge');
        const artist  = document.getElementById('artist');
        const title   = document.getElementById('title');
        const btnOpen = document.getElementById('btn-open');

        badge.style.display   = 'inline-block';
        artist.style.display  = 'block';
        title.style.display   = 'block';
        btnOpen.style.display = 'inline-block';

        const flag = song.lang === 'he' ? '🇮🇱' : '🇺🇸';
        badge.textContent  = flag + ' ' + song.source;
        artist.textContent = song.artist;
        title.textContent  = song.title;

        document.getElementById('counter').textContent =
          `${{pickCount}} pick${{pickCount !== 1 ? 's' : ''}} so far`;

        card.classList.remove('fade');
      }}, 250);
    }}

    function pickRandom() {{
      if (!songs.length) {{
        document.getElementById('hint').textContent =
          'No songs loaded — run fetch_favorites.py first.';
        return;
      }}
      showSong(songs[Math.floor(Math.random() * songs.length)]);
    }}

    function openSong() {{
      if (currentUrl) window.open(currentUrl, '_blank');
    }}

    function renderList(items) {{
      const list = document.getElementById('song-list');
      list.innerHTML = '';
      items.forEach(song => {{
        const row = document.createElement('button');
        row.className = 'song-row';
        const flag = song.lang === 'he' ? '🇮🇱' : '🇺🇸';
        row.innerHTML = `
          <span class="flag">${{flag}}</span>
          <span class="info">
            <span class="s-title">${{song.title}}</span>
            <span class="s-artist">${{song.artist}}</span>
          </span>`;
        row.onclick = () => {{ showSong(song); window.open(song.url, '_blank'); }};
        list.appendChild(row);
      }});
      document.getElementById('list-count').textContent =
        `${{items.length}} of ${{songs.length}} songs`;
    }}

    function renderFiltered() {{
      const q   = document.getElementById('search').value.toLowerCase();
      const key = document.getElementById('sort').value;
      let items = q
        ? songs.filter(s => s.title.toLowerCase().includes(q) || s.artist.toLowerCase().includes(q))
        : [...songs];
      if (key === 'random') items.sort(() => Math.random() - 0.5);
      else items.sort((a, b) => collator.compare(a[key], b[key]));
      renderList(items);
    }}

    // Render list on load
    renderFiltered();

    // Keyboard shortcut: Space = pick, Enter = open
    document.addEventListener('keydown', e => {{
      if (e.target.id === 'search') return;
      if (e.code === 'Space') {{ e.preventDefault(); pickRandom(); }}
      if (e.code === 'Enter' && currentUrl) openSong();
    }});
  </script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch guitar tab favorites and build a random picker page.")
    parser.add_argument(
        "--browser", default="chrome", choices=["chrome", "firefox"],
        help="Browser whose cookies to use (default: chrome)"
    )
    parser.add_argument("--ug-only",    action="store_true", help="Only fetch from Ultimate Guitar")
    parser.add_argument("--tab4u-only", action="store_true", help="Only fetch from Tab4u")
    parser.add_argument("--debug",      action="store_true", help="Dump raw page data for inspection")
    args = parser.parse_args()

    songs: list[dict] = []

    if not args.tab4u_only:
        try:
            songs.extend(fetch_ug_favorites(args.browser, args.debug))
        except Exception as e:
            print(f"  ✗ Ultimate Guitar error: {e}")

    if not args.ug_only:
        try:
            songs.extend(fetch_tab4u_favorites(args.browser, args.debug))
        except Exception as e:
            print(f"  ✗ Tab4u error: {e}")

    print(f"\nTotal songs collected: {len(songs)}")

    out = os.path.join(os.path.dirname(__file__), "random_song.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(generate_html(songs))

    print(f"Generated → {out}")
    print("Open it in your browser. Press Space to pick, Enter to open the tab.")
