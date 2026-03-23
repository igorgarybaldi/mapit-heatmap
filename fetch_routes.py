#!/usr/bin/env python3
"""
fetch_routes.py — Automated Mapit routes fetcher
=================================================
Fetches new routes directly from the Mapit API and regenerates routes.js.
Pure Python stdlib — no pip required.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FIRST-TIME SETUP (one-time, ~2 minutes)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. Open Chrome, go to app.mapit.me (logged in as Igor)
2. Open DevTools → Network tab (F12 → Network)
3. Click any button in the app to trigger a network request
4. Right-click any request to mapit.me → "Copy" → "Copy as cURL"
5. Run: python3 fetch_routes.py --setup
   Then paste the cURL command and press Ctrl+D

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WEEKLY USAGE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    python3 fetch_routes.py

Schedule weekly via cron (runs every Monday at 11:00):
    crontab -e
    Add: 0 11 * * 1 cd /Users/garybaldi2/Library/CloudStorage/Dropbox/Own/Claude/Cowork/Mapit && python3 fetch_routes.py >> fetch.log 2>&1

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
COOKIE EXPIRY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Cookies typically last 30–90 days. If you see "Auth failed", re-run --setup.
"""

import json
import re
import sys
import shlex
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

ROUTES_DIR   = Path(__file__).parent / 'routes'
COOKIES_FILE = Path(__file__).parent / 'mapit_cookies.json'
STATUS_FILE  = Path(__file__).parent / 'routes' / 'status.js'
VEHICLE_ID   = 'v-2c26shA02qUJ8zFyq5dK9Rrw3TJ'
API_URL      = f'https://geo.prod.mapit.me/v1/routes?vehicleId={VEHICLE_ID}'


def write_status(error=None, new_routes=0, total_routes=0):
    """Write routes/status.js so the HTML can show auth errors on load."""
    payload = {
        'error':       error,        # None | 'auth_expired' | 'network'
        'newRoutes':   new_routes,
        'totalRoutes': total_routes,
        'updatedAt':   datetime.now().isoformat(timespec='seconds'),
    }
    content = f"window.MAPIT_STATUS = {json.dumps(payload)};\n"
    with open(STATUS_FILE, 'w') as f:
        f.write(content)

# ── Cookie setup ──────────────────────────────────────────────────────────────

def setup_from_curl():
    """Parse a cURL command (from DevTools 'Copy as cURL') and save cookies + headers."""
    print("Paste the cURL command (from DevTools → Network → Copy as cURL).")
    print("Press Enter then Ctrl+D when done:\n")
    curl_cmd = sys.stdin.read().strip()

    # Extract cookie header from curl -H 'cookie: ...' or --cookie '...'
    cookies_str = None
    headers = {}

    # Parse all -H / --header flags
    # shlex handles multi-line and quoted strings
    try:
        tokens = shlex.split(curl_cmd.replace('\\\n', ' '))
    except ValueError:
        # fallback: basic regex
        tokens = curl_cmd.split()

    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in ('-H', '--header') and i + 1 < len(tokens):
            header = tokens[i + 1]
            if ':' in header:
                name, _, value = header.partition(':')
                name = name.strip().lower()
                value = value.strip()
                if name == 'cookie':
                    cookies_str = value
                elif name not in ('host',):  # keep useful headers
                    headers[name.title()] = value
            i += 2
        else:
            i += 1

    if not cookies_str:
        print("ERROR: No 'cookie' header found in the cURL command.")
        print("Make sure you used 'Copy as cURL' (not 'Copy as fetch') and the request had cookies.")
        sys.exit(1)

    # Parse cookie string into dict
    cookies = {}
    for part in cookies_str.split(';'):
        part = part.strip()
        if '=' in part:
            k, _, v = part.partition('=')
            cookies[k.strip()] = v.strip()

    saved = {
        'cookies': cookies,
        'headers': {k: v for k, v in headers.items()
                    if k.lower() in ('authorization', 'x-api-key', 'user-agent')},
        'saved_at': datetime.now().isoformat()
    }

    with open(COOKIES_FILE, 'w') as f:
        json.dump(saved, f, indent=2)

    print(f"\n✓ Saved {len(cookies)} cookies to {COOKIES_FILE.name}")
    print("  Cookie names:", ', '.join(cookies.keys()))
    print("\nSetup complete. Run 'python3 fetch_routes.py' to fetch routes.")


def load_auth():
    if not COOKIES_FILE.exists():
        print("ERROR: mapit_cookies.json not found.")
        print("First-time setup: python3 fetch_routes.py --setup")
        sys.exit(1)
    with open(COOKIES_FILE) as f:
        data = json.load(f)
    return data.get('cookies', {}), data.get('headers', {})

# ── API fetch ─────────────────────────────────────────────────────────────────

def fetch_routes_from_api(cookies, extra_headers):
    cookie_str = '; '.join(f'{k}={v}' for k, v in cookies.items())

    req = urllib.request.Request(API_URL, headers={
        'Cookie':     cookie_str,
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
        'Accept':     'application/json, text/plain, */*',
        'Referer':    'https://app.mapit.me/',
        'Origin':     'https://app.mapit.me',
        **extra_headers,
    })

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())['data']
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            write_status(error='auth_expired')
            print(f"ERROR: Auth failed (HTTP {e.code}). Cookies may have expired.")
            print("Re-run setup: python3 fetch_routes.py --setup")
            sys.exit(1)
        write_status(error='network')
        body = e.read().decode(errors='replace')[:500]
        print(f"ERROR: HTTP {e.code} from API: {body}")
        sys.exit(1)
    except urllib.error.URLError as e:
        write_status(error='network')
        print(f"ERROR: Network error: {e.reason}")
        print("Check your internet connection.")
        sys.exit(1)

# ── Route processing (shared logic with update_routes.py) ─────────────────────

def process_new_routes(routes_raw):
    existing_ids = {f.stem.split('_', 1)[1] for f in ROUTES_DIR.glob('*.json')}
    new_routes = []

    for r in routes_raw:
        if r['id'] in existing_ids:
            continue

        started  = datetime.fromisoformat(r['startedAt'].replace('Z', '+00:00'))
        ended    = datetime.fromisoformat(r['endedAt'].replace('Z', '+00:00'))
        date_str = r['startedAt'][:10]

        coords = []
        for feat in r['geoJSON']['features']:
            if feat['geometry']['type'] == 'LineString':
                for c in feat['geometry']['coordinates']:
                    coords.append([round(c[1], 6), round(c[0], 6)])

        if not coords:
            continue

        route_obj = {
            'id':        r['id'],
            'date':      date_str,
            'dayOfWeek': started.isoweekday() - 1,  # 0=Mon, 6=Sun
            'distance':  round(r.get('distance', 0) / 1000, 3),
            'duration':  round((ended - started).seconds / 60, 1),
            'maxSpeed':  r.get('maxSpeed', None),
            'avgSpeed':  r.get('avgSpeed', None),
            'coords':    coords,
        }

        fname = f"{date_str}_{r['id']}.json"
        with open(ROUTES_DIR / fname, 'w') as fout:
            json.dump(route_obj, fout, separators=(',', ':'))
        new_routes.append(route_obj)

    return new_routes


def regenerate_routes_js():
    all_routes = []
    for f in sorted(ROUTES_DIR.glob('*.json')):
        with open(f) as fp:
            all_routes.append(json.load(fp))

    all_routes.sort(key=lambda x: x['date'])
    min_date = all_routes[0]['date']
    max_date = all_routes[-1]['date']

    content = (
        f"// Generated by fetch_routes.py — {len(all_routes)} routes "
        f"({min_date} → {max_date})\n"
        f"window.ROUTES_DATA = {json.dumps(all_routes, separators=(',', ':'))};\n"
    )

    out_path = ROUTES_DIR / 'routes.js'
    with open(out_path, 'w') as f:
        f.write(content)

    return len(all_routes), min_date, max_date

# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    ROUTES_DIR.mkdir(exist_ok=True)

    if '--setup' in sys.argv:
        setup_from_curl()
        sys.exit(0)

    ts = datetime.now().strftime('%Y-%m-%d %H:%M')
    print(f"[{ts}] Fetching routes from Mapit API...")

    cookies, extra_headers = load_auth()
    routes_raw = fetch_routes_from_api(cookies, extra_headers)
    new_routes = process_new_routes(routes_raw)

    total = len(routes_raw)
    new   = len(new_routes)
    print(f"  API returned {total} routes total, {new} new")

    if new > 0:
        count, min_date, max_date = regenerate_routes_js()
        write_status(new_routes=new, total_routes=count)
        print(f"  ✓ routes.js updated: {count} routes ({min_date} → {max_date})")
        if new_routes:
            print(f"  New routes: {', '.join(r['date'] for r in new_routes)}")
    else:
        count = sum(1 for _ in ROUTES_DIR.glob('*.json'))
        write_status(new_routes=0, total_routes=count)
        print("  Already up to date — no changes.")
