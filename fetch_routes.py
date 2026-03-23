#!/usr/bin/env python3
"""
fetch_routes.py — Automated Mapit routes fetcher
=================================================
Fetches new routes from the Mapit API using AWS Cognito auth.
Pure Python stdlib — no pip required.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FIRST-TIME SETUP (one-time, ~2 minutes)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. Open Chrome, go to app.mapit.me (logged in)
2. Open DevTools (F12) → Console tab
3. Paste this and press Enter:
     copy(localStorage.getItem(Object.keys(localStorage).find(k=>k.includes('refreshToken'))))
4. Run: python3 fetch_routes.py --setup
5. Paste the refresh token and press Enter

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WEEKLY USAGE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    python3 fetch_routes.py

Runs automatically every Monday via GitHub Actions.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TOKEN EXPIRY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Refresh tokens last ~30 days. If you see "Auth failed", re-run --setup.
"""

import json
import hmac
import hashlib
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

# ── Config ────────────────────────────────────────────────────────────────────

ROUTES_DIR    = Path(__file__).parent / 'routes'
AUTH_FILE     = Path(__file__).parent / 'mapit_cookies.json'
STATUS_FILE   = Path(__file__).parent / 'routes' / 'status.js'
VEHICLE_ID    = 'v-2c26shA02qUJ8zFyq5dK9Rrw3TJ'
API_URL       = f'https://geo.prod.mapit.me/v1/routes?vehicleId={VEHICLE_ID}'

# AWS Cognito config (from Mapit app)
COGNITO_REGION    = 'eu-west-1'
COGNITO_CLIENT_ID = '7fo1dt507lf6riggmprmql2mpb'
COGNITO_USER_POOL = f'cognito-idp.{COGNITO_REGION}.amazonaws.com/eu-west-1_nHd6Er8N6'
COGNITO_IDP_URL   = f'https://cognito-idp.{COGNITO_REGION}.amazonaws.com/'
COGNITO_ID_URL    = f'https://cognito-identity.{COGNITO_REGION}.amazonaws.com/'

# Identity pool ID — discovered from Mapit app JS bundle
IDENTITY_POOL_ID  = 'eu-west-1:a25d1457-542f-43d3-8b47-c3c60ed3675d'


def write_status(error=None, new_routes=0, total_routes=0):
    """Write routes/status.js so the HTML can show auth errors on load."""
    payload = {
        'error':       error,
        'newRoutes':   new_routes,
        'totalRoutes': total_routes,
        'updatedAt':   datetime.now().isoformat(timespec='seconds'),
    }
    content = f"window.MAPIT_STATUS = {json.dumps(payload)};\n"
    with open(STATUS_FILE, 'w') as f:
        f.write(content)


# ── AWS Signature V4 ─────────────────────────────────────────────────────────

def _sign(key, msg):
    return hmac.new(key, msg.encode('utf-8'), hashlib.sha256).digest()


def aws_sigv4_headers(method, url, access_key, secret_key, session_token, region, service):
    """Generate AWS Signature V4 auth headers for a request."""
    parsed = urlparse(url)
    host = parsed.hostname
    path = parsed.path or '/'
    query = parsed.query

    now = datetime.now(timezone.utc)
    amz_date = now.strftime('%Y%m%dT%H%M%SZ')
    date_stamp = now.strftime('%Y%m%d')

    # Headers to sign (must be sorted)
    headers_to_sign = {
        'accept': 'application/json',
        'host': host,
        'x-amz-date': amz_date,
    }

    signed_headers_str = ';'.join(sorted(headers_to_sign.keys()))
    canonical_headers = ''.join(f'{k}:{v}\n' for k, v in sorted(headers_to_sign.items()))
    payload_hash = hashlib.sha256(b'').hexdigest()

    canonical_request = (
        f'{method}\n{path}\n{query}\n{canonical_headers}\n'
        f'{signed_headers_str}\n{payload_hash}'
    )

    credential_scope = f'{date_stamp}/{region}/{service}/aws4_request'
    string_to_sign = (
        f'AWS4-HMAC-SHA256\n{amz_date}\n{credential_scope}\n'
        f'{hashlib.sha256(canonical_request.encode()).hexdigest()}'
    )

    k_date    = _sign(f'AWS4{secret_key}'.encode('utf-8'), date_stamp)
    k_region  = _sign(k_date, region)
    k_service = _sign(k_region, service)
    k_signing = _sign(k_service, 'aws4_request')
    signature = hmac.new(k_signing, string_to_sign.encode('utf-8'), hashlib.sha256).hexdigest()

    return {
        'Authorization': (
            f'AWS4-HMAC-SHA256 Credential={access_key}/{credential_scope}, '
            f'SignedHeaders={signed_headers_str}, Signature={signature}'
        ),
        'X-Amz-Date': amz_date,
        'X-Amz-Security-Token': session_token,
    }


# ── Cognito auth flow ────────────────────────────────────────────────────────

def _cognito_call(url, target, payload):
    """Make a Cognito API call."""
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, headers={
        'Content-Type': 'application/x-amz-json-1.1',
        'X-Amz-Target': target,
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode(errors='replace')[:500]
        raise RuntimeError(f"Cognito {target} failed (HTTP {e.code}): {error_body}")


def refresh_cognito_tokens(refresh_token):
    """Use refresh token to get fresh id_token + access_token."""
    result = _cognito_call(
        COGNITO_IDP_URL,
        'AWSCognitoIdentityProviderService.InitiateAuth',
        {
            'AuthFlow': 'REFRESH_TOKEN_AUTH',
            'ClientId': COGNITO_CLIENT_ID,
            'AuthParameters': {'REFRESH_TOKEN': refresh_token},
        }
    )
    auth = result['AuthenticationResult']
    return auth['IdToken'], auth.get('AccessToken', '')


def get_aws_credentials(id_token, identity_pool_id):
    """Exchange Cognito id_token for temporary AWS credentials."""
    # Step 1: Get identity ID
    id_result = _cognito_call(
        COGNITO_ID_URL,
        'AWSCognitoIdentityService.GetId',
        {
            'IdentityPoolId': identity_pool_id,
            'Logins': {COGNITO_USER_POOL: id_token},
        }
    )
    identity_id = id_result['IdentityId']

    # Step 2: Get credentials
    creds_result = _cognito_call(
        COGNITO_ID_URL,
        'AWSCognitoIdentityService.GetCredentialsForIdentity',
        {
            'IdentityId': identity_id,
            'Logins': {COGNITO_USER_POOL: id_token},
        }
    )
    creds = creds_result['Credentials']
    return creds['AccessKeyId'], creds['SecretKey'], creds['SessionToken']


# ── Setup ─────────────────────────────────────────────────────────────────────

def setup():
    """Interactive setup: save refresh token and discover identity pool."""
    print("━━━ Mapit Auth Setup ━━━\n")

    # Get refresh token
    print("1. Open Chrome → app.mapit.me (logged in)")
    print("2. DevTools (F12) → Console tab")
    print("3. Paste this command and press Enter:\n")
    print("   copy(localStorage.getItem(Object.keys(localStorage).find(k=>k.includes('refreshToken'))))\n")
    print("4. Now paste the refresh token here (it's in your clipboard):")
    refresh_token = input("   > ").strip()

    if not refresh_token or len(refresh_token) < 100:
        print("ERROR: That doesn't look like a valid refresh token.")
        sys.exit(1)

    # Get identity pool ID
    print("\n5. Now paste this in the Console:\n")
    print("   copy(Object.keys(localStorage).find(k=>k.startsWith('aws.cognito.identity-id')).split('.').pop())\n")
    print("6. Paste the identity pool ID here:")
    identity_pool_id = input("   > ").strip()

    if not identity_pool_id or ':' not in identity_pool_id:
        print("ERROR: That doesn't look like a valid identity pool ID (expected format: eu-west-1:uuid).")
        sys.exit(1)

    # Verify the tokens work
    print("\n  Verifying tokens...", end=' ', flush=True)
    try:
        id_token, _ = refresh_cognito_tokens(refresh_token)
        print("✓ Token refresh OK")
        print("  Getting AWS credentials...", end=' ', flush=True)
        ak, sk, st = get_aws_credentials(id_token, identity_pool_id)
        print("✓ AWS credentials OK")
    except Exception as e:
        print(f"\n  ERROR: Verification failed: {e}")
        sys.exit(1)

    # Save
    saved = {
        'refresh_token':   refresh_token,
        'identity_pool_id': identity_pool_id,
        'saved_at':         datetime.now().isoformat(),
    }
    with open(AUTH_FILE, 'w') as f:
        json.dump(saved, f, indent=2)

    print(f"\n✓ Auth saved to {AUTH_FILE.name}")
    print("  Run 'python3 fetch_routes.py' to fetch routes.")


def load_auth():
    """Load saved refresh token and identity pool ID."""
    if not AUTH_FILE.exists():
        print("ERROR: mapit_cookies.json not found.")
        print("First-time setup: python3 fetch_routes.py --setup")
        sys.exit(1)
    with open(AUTH_FILE) as f:
        data = json.load(f)

    refresh_token = data.get('refresh_token')
    identity_pool_id = data.get('identity_pool_id')

    if not refresh_token:
        print("ERROR: No refresh_token in auth file. Re-run: python3 fetch_routes.py --setup")
        sys.exit(1)
    if not identity_pool_id:
        print("ERROR: No identity_pool_id in auth file. Re-run: python3 fetch_routes.py --setup")
        sys.exit(1)

    return refresh_token, identity_pool_id


# ── API fetch ─────────────────────────────────────────────────────────────────

def fetch_routes_from_api(refresh_token, identity_pool_id):
    """Authenticate via Cognito and fetch routes from Mapit API."""
    # Step 1: Refresh tokens
    try:
        id_token, _ = refresh_cognito_tokens(refresh_token)
    except RuntimeError as e:
        if 'NotAuthorizedException' in str(e):
            write_status(error='auth_expired')
            print(f"ERROR: Refresh token expired. Re-run: python3 fetch_routes.py --setup")
            sys.exit(1)
        raise

    # Step 2: Get AWS credentials
    access_key, secret_key, session_token = get_aws_credentials(id_token, identity_pool_id)

    # Step 3: Sign the request
    sig_headers = aws_sigv4_headers(
        'GET', API_URL, access_key, secret_key, session_token,
        COGNITO_REGION, 'execute-api'
    )

    req = urllib.request.Request(API_URL, headers={
        'Accept':      'application/json',
        'Origin':      'https://app.mapit.me',
        'Referer':     'https://app.mapit.me/',
        'User-Agent':  'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                       'AppleWebKit/537.36 Chrome/123.0.0.0 Safari/537.36',
        'X-Id-Token':  id_token,
        **sig_headers,
    })

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())['data']
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            write_status(error='auth_expired')
            print(f"ERROR: Auth failed (HTTP {e.code}). Token may have expired.")
            print("Re-run setup: python3 fetch_routes.py --setup")
            sys.exit(1)
        write_status(error='network')
        body = e.read().decode(errors='replace')[:500]
        print(f"ERROR: HTTP {e.code} from API: {body}")
        sys.exit(1)
    except urllib.error.URLError as e:
        write_status(error='network')
        print(f"ERROR: Network error: {e.reason}")
        sys.exit(1)


# ── Route processing ─────────────────────────────────────────────────────────

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
            'dayOfWeek': started.isoweekday() - 1,
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
        setup()
        sys.exit(0)

    ts = datetime.now().strftime('%Y-%m-%d %H:%M')
    print(f"[{ts}] Fetching routes from Mapit API...")

    refresh_token, identity_pool_id = load_auth()
    routes_raw = fetch_routes_from_api(refresh_token, identity_pool_id)
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
