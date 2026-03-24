#!/usr/bin/env python3
"""
fetch_routes.py — Automated Mapit routes fetcher
=================================================
Fetches new routes from the Mapit API using Cognito password auth.
Pure Python stdlib — no pip required.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FULLY AUTOMATED — zero manual steps
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Auth via email + password (env vars or local file).
No tokens to refresh, no cookies, no browser needed.

GitHub Actions: set MAPIT_EMAIL + MAPIT_PASSWORD secrets.
Local: set env vars, or create mapit_cookies.json with email/password.
"""

import json
import hmac
import hashlib
import os
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
IDENTITY_POOL_ID  = 'eu-west-1:a25d1457-542f-43d3-8b47-c3c60ed3675d'


def write_status(error=None, new_routes=0, total_routes=0):
    payload = {
        'error':       error,
        'newRoutes':   new_routes,
        'totalRoutes': total_routes,
        'updatedAt':   datetime.now().isoformat(timespec='seconds'),
    }
    with open(STATUS_FILE, 'w') as f:
        f.write(f"window.MAPIT_STATUS = {json.dumps(payload)};\n")


# ── AWS Signature V4 ─────────────────────────────────────────────────────────

def _hmac_sign(key, msg):
    return hmac.new(key, msg.encode('utf-8'), hashlib.sha256).digest()


def aws_sigv4_headers(method, url, access_key, secret_key, session_token, region, service):
    parsed = urlparse(url)
    host = parsed.hostname
    path = parsed.path or '/'
    query = parsed.query

    now = datetime.now(timezone.utc)
    amz_date = now.strftime('%Y%m%dT%H%M%SZ')
    date_stamp = now.strftime('%Y%m%d')

    headers_to_sign = {'accept': 'application/json', 'host': host, 'x-amz-date': amz_date}
    signed_headers_str = ';'.join(sorted(headers_to_sign.keys()))
    canonical_headers = ''.join(f'{k}:{v}\n' for k, v in sorted(headers_to_sign.items()))
    payload_hash = hashlib.sha256(b'').hexdigest()

    canonical_request = f'{method}\n{path}\n{query}\n{canonical_headers}\n{signed_headers_str}\n{payload_hash}'
    credential_scope = f'{date_stamp}/{region}/{service}/aws4_request'
    string_to_sign = f'AWS4-HMAC-SHA256\n{amz_date}\n{credential_scope}\n{hashlib.sha256(canonical_request.encode()).hexdigest()}'

    k_date    = _hmac_sign(f'AWS4{secret_key}'.encode('utf-8'), date_stamp)
    k_region  = _hmac_sign(k_date, region)
    k_service = _hmac_sign(k_region, service)
    k_signing = _hmac_sign(k_service, 'aws4_request')
    signature = hmac.new(k_signing, string_to_sign.encode('utf-8'), hashlib.sha256).hexdigest()

    return {
        'Authorization': f'AWS4-HMAC-SHA256 Credential={access_key}/{credential_scope}, SignedHeaders={signed_headers_str}, Signature={signature}',
        'X-Amz-Date': amz_date,
        'X-Amz-Security-Token': session_token,
    }


# ── Cognito auth ──────────────────────────────────────────────────────────────

def _cognito_call(url, target, payload):
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


def login_with_password(email, password):
    """Authenticate with email + password. Returns id_token."""
    result = _cognito_call(
        COGNITO_IDP_URL,
        'AWSCognitoIdentityProviderService.InitiateAuth',
        {
            'AuthFlow': 'USER_PASSWORD_AUTH',
            'ClientId': COGNITO_CLIENT_ID,
            'AuthParameters': {'USERNAME': email, 'PASSWORD': password},
        }
    )
    return result['AuthenticationResult']['IdToken']


def get_aws_credentials(id_token):
    """Exchange Cognito id_token for temporary AWS credentials."""
    id_result = _cognito_call(
        COGNITO_ID_URL, 'AWSCognitoIdentityService.GetId',
        {'IdentityPoolId': IDENTITY_POOL_ID, 'Logins': {COGNITO_USER_POOL: id_token}},
    )
    creds_result = _cognito_call(
        COGNITO_ID_URL, 'AWSCognitoIdentityService.GetCredentialsForIdentity',
        {'IdentityId': id_result['IdentityId'], 'Logins': {COGNITO_USER_POOL: id_token}},
    )
    c = creds_result['Credentials']
    return c['AccessKeyId'], c['SecretKey'], c['SessionToken']


# ── Auth loading ──────────────────────────────────────────────────────────────

def get_credentials():
    """Get email + password from env vars or local file."""
    email = os.environ.get('MAPIT_EMAIL')
    password = os.environ.get('MAPIT_PASSWORD')

    if email and password:
        return email, password

    if AUTH_FILE.exists():
        with open(AUTH_FILE) as f:
            data = json.load(f)
        email = data.get('email')
        password = data.get('password')
        if email and password:
            return email, password

    print("ERROR: No credentials found.")
    print("Set MAPIT_EMAIL + MAPIT_PASSWORD env vars.")
    sys.exit(1)


# ── API fetch ─────────────────────────────────────────────────────────────────

def fetch_routes_from_api():
    email, password = get_credentials()

    print("  Auth: Cognito login...", end=' ', flush=True)
    try:
        id_token = login_with_password(email, password)
        print("✓")
    except RuntimeError as e:
        if 'NotAuthorizedException' in str(e):
            write_status(error='auth_expired')
            print(f"\n  ERROR: Wrong email/password.")
            sys.exit(1)
        raise

    access_key, secret_key, session_token = get_aws_credentials(id_token)

    sig_headers = aws_sigv4_headers(
        'GET', API_URL, access_key, secret_key, session_token,
        COGNITO_REGION, 'execute-api'
    )

    req = urllib.request.Request(API_URL, headers={
        'Accept':      'application/json',
        'Origin':      'https://app.mapit.me',
        'Referer':     'https://app.mapit.me/',
        'User-Agent':  'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        'X-Id-Token':  id_token,
        **sig_headers,
    })

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())['data']
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            write_status(error='auth_expired')
            print(f"ERROR: Auth failed (HTTP {e.code}).")
            sys.exit(1)
        write_status(error='network')
        print(f"ERROR: HTTP {e.code}: {e.read().decode(errors='replace')[:500]}")
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
            'id': r['id'], 'date': date_str,
            'dayOfWeek': started.isoweekday() - 1,
            'distance': round(r.get('distance', 0) / 1000, 3),
            'duration': round((ended - started).seconds / 60, 1),
            'maxSpeed': r.get('maxSpeed', None),
            'avgSpeed': r.get('avgSpeed', None),
            'coords': coords,
        }

        with open(ROUTES_DIR / f"{date_str}_{r['id']}.json", 'w') as fout:
            json.dump(route_obj, fout, separators=(',', ':'))
        new_routes.append(route_obj)

    return new_routes


def regenerate_routes_js():
    all_routes = []
    for f in sorted(ROUTES_DIR.glob('*.json')):
        with open(f) as fp:
            all_routes.append(json.load(fp))

    all_routes.sort(key=lambda x: x['date'])
    min_date, max_date = all_routes[0]['date'], all_routes[-1]['date']

    with open(ROUTES_DIR / 'routes.js', 'w') as f:
        f.write(f"// Generated by fetch_routes.py — {len(all_routes)} routes ({min_date} → {max_date})\n")
        f.write(f"window.ROUTES_DATA = {json.dumps(all_routes, separators=(',', ':'))};\n")

    return len(all_routes), min_date, max_date


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    ROUTES_DIR.mkdir(exist_ok=True)

    ts = datetime.now().strftime('%Y-%m-%d %H:%M')
    print(f"[{ts}] Fetching routes from Mapit API...")

    routes_raw = fetch_routes_from_api()
    new_routes = process_new_routes(routes_raw)

    total, new = len(routes_raw), len(new_routes)
    print(f"  API returned {total} routes total, {new} new")

    if new > 0:
        count, min_date, max_date = regenerate_routes_js()
        write_status(new_routes=new, total_routes=count)
        print(f"  ✓ routes.js updated: {count} routes ({min_date} → {max_date})")
        print(f"  New routes: {', '.join(r['date'] for r in new_routes)}")
    else:
        count = sum(1 for _ in ROUTES_DIR.glob('*.json'))
        write_status(new_routes=0, total_routes=count)
        print("  Already up to date — no changes.")
