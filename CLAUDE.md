# Mapit Journey Heatmap — Project Context

## What this project is
An interactive heatmap of Igor's motorcycle journeys, built from data exported from [Mapit by Honda](https://app.mapit.me/). A password-protected single-page app hosted on GitHub Pages at **https://moto.garybaldi.xyz**. Routes auto-update weekly via GitHub Actions.

---

## Live Site

| Field | Value |
|-------|-------|
| URL | https://moto.garybaldi.xyz |
| Password | `Moto527` (SHA-256 hashed in `index.html`) |
| Cookie | `mapit_auth=1`, expires 30 days |
| Hosting | GitHub Pages (repo: `igorgarybaldi/mapit-heatmap`) |
| Auto-deploy | On push to `main` branch |

To change the password: compute new SHA-256 hash, update the `PWD_HASH` constant in `index.html`, push.

---

## Vehicle & Account

| Field            | Value                                      |
|------------------|--------------------------------------------|
| Model            | Honda WW125AP (PCX 125)                    |
| Plate            | 8489 MND                                   |
| Vehicle ID       | `v-2c26shA02qUJ8zFyq5dK9Rrw3TJ`           |
| Device ID        | `d-2WWA9bFRMR0MkjvTbAfJb5Lfz00`           |
| Account ID       | `a-2bgeEzQ0VUsQjYLNwxXHBAlJ26m`           |
| Email            | igordebarcelona@gmail.com                  |
| Location         | Barcelona, Spain (~41.39°N, 2.17°E)        |

---

## Folder Structure

```
Mapit/
  index.html                    ← Main app (was journey_heatmap.html)
  fetch_routes.py               ← Automated API fetcher (Cognito + SigV4 auth)
  update_routes.py              ← Regenerate routes.js from existing JSONs / import from HAR
  CLAUDE.md                     ← This file
  CNAME                         ← Custom domain for GitHub Pages
  .gitignore                    ← Excludes cookies, cache, old files
  .github/
    workflows/
      fetch-routes.yml          ← Weekly GitHub Actions cron job
  routes/
    routes.js                   ← Auto-generated aggregated data (loaded by HTML via <script>)
    status.js                   ← Fetch status (error state, new route count, timestamp)
    2024-02-20_rt-xxxx.json     ← One JSON file per route (783 total as of Mar 2026)
    ...
```

Old files (in .gitignore, can be deleted):
- `journey_heatmap_march2026.html` — first prototype
- `journey_heatmap_full_history.html` — second version
- `journey_heatmap.html` — pre-rename version of index.html

---

## Data Pipeline — Automated (Primary)

Routes are fetched automatically every Monday via GitHub Actions.

### How it works
```
Every Monday 09:00 UTC (11:00 Barcelona):
  GitHub Actions → fetch_routes.py → Cognito auth → Mapit API → new route JSONs
  → regenerate routes.js + status.js → git commit + push → GitHub Pages auto-deploys
```

### Workflow file: `.github/workflows/fetch-routes.yml`
- Schedule: `cron: '0 9 * * 1'` (Monday 09:00 UTC)
- Also supports manual trigger via GitHub UI (Actions → Run workflow)
- Auth: `MAPIT_REFRESH_TOKEN` GitHub Secret (env var, not file)
- Identity Pool ID: hardcoded in `fetch_routes.py`

### Auth flow (AWS Cognito)
The Mapit API uses AWS API Gateway with IAM auth. The full flow:
1. **Refresh token** → Cognito `InitiateAuth` → fresh `id_token`
2. **id_token** → Cognito Identity `GetId` → `identity_id`
3. **identity_id + id_token** → Cognito Identity `GetCredentialsForIdentity` → temp AWS creds
4. **AWS creds** → SigV4 sign the API request → call routes endpoint

### AWS Cognito config
| Field | Value |
|-------|-------|
| Region | `eu-west-1` |
| User Pool | `eu-west-1_nHd6Er8N6` |
| Client ID | `7fo1dt507lf6riggmprmql2mpb` |
| Identity Pool | `eu-west-1:a25d1457-542f-43d3-8b47-c3c60ed3675d` |

### When refresh token expires (~30 days)
The map shows an error banner. To fix:
1. Open Chrome → app.mapit.me (logged in)
2. DevTools (F12) → Console → run:
   ```
   copy(localStorage.getItem(Object.keys(localStorage).find(k=>k.includes('refreshToken'))))
   ```
3. Go to GitHub → repo Settings → Secrets → Actions → update `MAPIT_REFRESH_TOKEN`
4. Optionally trigger workflow manually to verify

### Local usage
```bash
# First-time setup:
python3 fetch_routes.py --setup

# Manual fetch:
python3 fetch_routes.py
```
Auth saved to `mapit_cookies.json` (gitignored). Script reads env var `MAPIT_REFRESH_TOKEN` first, falls back to file.

---

## Data Pipeline — Manual (Fallback)

If automated fetch breaks, routes can still be imported from HAR files.

### Step 1 — Export HAR from Chrome
1. Open `https://app.mapit.me/` in Chrome (logged in)
2. DevTools → Network tab → Clear
3. Click the **Journeys** button
4. Export as HAR file (`⋮` → Save all as HAR with content)

### Step 2 — Import
```bash
python3 update_routes.py --from-har path/to/export.har
```

### Step 3 — Push
```bash
git add routes/ && git commit -m "Update routes" && git push
```

---

## Mapit API

| Endpoint | Description |
|----------|-------------|
| `https://core.prod.mapit.me/v1/accounts?email=EMAIL` | Account info |
| `https://core.prod.mapit.me/v1/accounts/ACCOUNT_ID/summary` | Full account summary |
| `https://core.prod.mapit.me/v1/vehicles/VEHICLE_ID` | Vehicle details, odometer |
| `https://geo.prod.mapit.me/v1/routes?vehicleId=VEHICLE_ID` | **All routes with full GPS** |
| `wss://dsw.prod.mapit.me/devicestate/DEVICE_ID` | Live device state (WebSocket) |

The routes endpoint returns GeoJSON with `LineString` features per route. All routes (full history) come in one response — no pagination observed.

Auth: AWS Cognito tokens + SigV4 signed requests (see auth flow above).

---

## Route JSON Schema

Each file in `routes/` follows this schema:

```json
{
  "id":        "rt-1w2UGIXq4mwscHVGNT5175We0dj",
  "date":      "2026-03-17",
  "dayOfWeek": 0,
  "distance":  2.323,
  "duration":  11.7,
  "maxSpeed":  45,
  "avgSpeed":  11,
  "coords":    [[41.39053, 2.19029], ...]
}
```

- `dayOfWeek`: 0 = Monday … 6 = Sunday
- `coords`: `[lat, lng]` pairs (GeoJSON source is `[lng, lat]`, already flipped)
- `maxSpeed` / `avgSpeed`: null for older routes (~544/783 missing)
- `distance`: in km
- Filename format: `{date}_{id}.json`

---

## HTML App Architecture

### How data loads
```html
<script src="routes/routes.js"></script>   <!-- sets window.ROUTES_DATA = [...] -->
<script src="routes/status.js"></script>   <!-- sets window.MAPIT_STATUS = {...} -->
```

### Password gate
Full-screen overlay on load. Password checked against SHA-256 hash. On success, sets `mapit_auth` cookie (30 days). On next visit, cookie skips the gate.

### Status notifications
- **Auth error banner**: shown when `MAPIT_STATUS.error === 'auth_expired'`. Red banner with instructions.
- **New routes toast**: shown when `MAPIT_STATUS.newRoutes > 0`. Purple toast top-right with dismiss X.

### Filter logic
Filters work by **setting opacity to 0** on hidden polylines (not removing from map) — much faster than add/remove for 783 layers. Heatmap is rebuilt from filtered coords on each filter change (debounced at 120ms for sliders).

### Stats
Header stats (journeys, total km, GPS points, top speed, avg speed) **update dynamically** based on active filters. Journeys shows `filtered / total` format.

### UI Elements (IDs)

**Header (desktop):**
- `#sv-routes`, `#sv-km`, `#sv-pts`, `#sv-spd`, `#sv-avg` — stat values
- `#btn-dark`, `#btn-light` — theme toggle (SVG icons, text hidden on mobile)

**Mobile header:**
- `#mobile-dashboard-btn` — opens stats drawer from top
- `#mobile-filters-btn` — opens filters drawer from bottom (left)
- `#mobile-controls-btn` — opens view/controls drawer from bottom (right)
- Bottom drawers have close X buttons, only one open at a time

**Filters panel (`#filters-panel`):**
- `#date-from`, `#date-to` — date range inputs
- `#dist-min`, `#dist-max` — distance range sliders (0–39 km)
- `.day-cb` (×7) — day-of-week checkboxes
- Collapsible: `+` when collapsed, `−` when expanded (desktop)

**View panel (`#controls-panel`):**
- `#chk-heat`, `#chk-routes` — layer visibility toggles
- `#sl-heat-opacity` — heatmap opacity slider
- `#sl-radius`, `#sl-blur` — heatmap appearance sliders
- `#sl-opacity` — route line opacity slider
- Collapsible (desktop), renamed from "Controls" to "View"

**Tooltip (`#tooltip`):**
- `#tt-date`, `#tt-dist`, `#tt-dur`, `#tt-max`, `#tt-avg`

### Map tiles
```javascript
const TILE_LAYERS = {
  dark:  'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
  light: 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png'
};
```

### Route line colours
```javascript
const LINE_COLOR = { dark: '#ff6b35', light: '#d35400' };
```
Hover highlight: `#ffffff` (both themes).

### Heatmap gradient (blue hues only)
```javascript
{ 0.2: '#1a0a3e', 0.4: '#3b1f8e', 0.6: '#5b3cc4', 0.8: '#6e6ef7', 1.0: '#9d8cff' }
```

### CSS theming
Body class `theme-dark` / `theme-light`. Key custom properties:

| Property | Dark | Light |
|----------|------|-------|
| Background | `#1A191C` | `#f0f0f5` |
| `--accent` | `#8D69F3` | `#7044cc` |
| `--panel-bg` | `rgba(22,21,25,0.96)` | `rgba(255,255,255,0.96)` |
| `--thumb` (slider handle) | `#d4d4d4` | `#555` |
| `--track-bg` | `rgba(255,255,255,0.12)` | `rgba(0,0,0,0.12)` |

Active UI elements (sliders, checkboxes) use `--accent` (`#8D69F3`).

---

## Dataset Stats (as of Mar 2026)

| Metric | Value |
|--------|-------|
| Total routes | 783 |
| Date range | 2024-02-20 → 2026-03-17 |
| Total GPS points | 18,071 |
| Total distance | ~2,943 km |
| Max single route | 38.7 km |
| Top speed recorded | 87 km/h |
| routes.js size | ~489 KB |

---

## External Libraries (CDN)

```html
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://unpkg.com/leaflet.heat@0.2.0/dist/leaflet-heat.js"></script>
```

No build tools, no npm, no server required.

> **Note:** pip/npm installs are blocked in this environment (proxy restriction). All dependencies must be CDN-loaded or pure Python stdlib.

---

## GitHub Repository

| Field | Value |
|-------|-------|
| Repo | `igorgarybaldi/mapit-heatmap` (public) |
| Branch | `main` |
| Pages | Enabled, custom domain `moto.garybaldi.xyz` |
| Secret | `MAPIT_REFRESH_TOKEN` — Cognito refresh token |
| Action | `Fetch Mapit Routes` — weekly Monday 09:00 UTC |

### Files in repo
Everything except: `mapit_cookies.json`, `__pycache__/`, `.claude/`, `*.har`, `*.log`, old HTML versions.

### Pushing changes
```bash
cd "/Users/garybaldi2/Library/CloudStorage/Dropbox/Own/Claude/Cowork/Mapit"
git add <files> && git commit -m "message" && git push
```
GitHub Pages auto-deploys within ~1 minute of push.
