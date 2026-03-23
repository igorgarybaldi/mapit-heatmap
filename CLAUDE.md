# Mapit Journey Heatmap — Project Context

## What this project is
An interactive heatmap of Igor's motorcycle journeys, built from data exported from [Mapit by Honda](https://app.mapit.me/). The page is a single self-contained HTML file that loads route GPS data from a local `routes/` folder and renders it on an interactive Leaflet.js map with filters, heatmap, and route lines.

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
  journey_heatmap.html          ← Main app — open this in browser
  update_routes.py              ← Run to regenerate routes.js after adding new route JSONs
  CLAUDE.md                     ← This file
  routes/
    routes.js                   ← Auto-generated aggregated data (loaded by HTML via <script>)
    2024-02-20_rt-xxxx.json     ← One JSON file per route (783 total as of Mar 2026)
    ...
```

Old files (can be ignored/deleted):
- `journey_heatmap_march2026.html` — first prototype, last 30 days only
- `journey_heatmap_full_history.html` — second version, no filters

---

## Data Pipeline

### Step 1 — Get new route data from Mapit
The app doesn't have a direct CSV/GPX export. Data is obtained via HAR export:
1. Open `https://app.mapit.me/` in Chrome (must be logged in as Igor)
2. Open DevTools → Network tab → Clear
3. Click the **Journeys** button in the app to load the journey list
4. In DevTools, export as HAR file (`⋮` → Save all as HAR with content)

### Step 2 — Import new routes
```bash
python3 update_routes.py --from-har path/to/new_export.har
```
This will:
- Parse the HAR for the routes API response (`geo.prod.mapit.me/v1/routes`)
- Skip routes already saved (deduplication by route ID)
- Save new routes as individual JSONs in `routes/`
- Regenerate `routes/routes.js`

### Step 3 — Refresh the page
Just reload `journey_heatmap.html` in the browser — it reads `routes/routes.js` on load.

---

## Mapit API (discovered from HAR)

| Endpoint | Description |
|----------|-------------|
| `https://core.prod.mapit.me/v1/accounts?email=EMAIL` | Account info |
| `https://core.prod.mapit.me/v1/accounts/ACCOUNT_ID/summary` | Full account summary |
| `https://core.prod.mapit.me/v1/vehicles/VEHICLE_ID` | Vehicle details, odometer |
| `https://geo.prod.mapit.me/v1/routes?vehicleId=VEHICLE_ID` | **All routes with full GPS** |
| `wss://dsw.prod.mapit.me/devicestate/DEVICE_ID` | Live device state (WebSocket) |

The routes endpoint returns GeoJSON with `LineString` features per route. All routes (full history) come in one response — no pagination observed. The HAR captured 783 routes (Feb 2024 → Mar 2026) in a single 1.4MB response.

Auth is cookie-based (session from browser login). The HAR file captures the auth headers automatically.

---

## Route JSON Schema

Each file in `routes/` follows this schema (pre-processed from the raw API response):

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

- `dayOfWeek`: 0 = Monday … 6 = Sunday (Python `isoweekday() - 1`)
- `coords`: `[lat, lng]` pairs (note: GeoJSON source is `[lng, lat]`, already flipped)
- `maxSpeed` / `avgSpeed`: null for older routes (~544/783 are missing these)
- `distance`: in km (API gives metres, divided by 1000)
- Filename format: `{date}_{id}.json`

---

## HTML App Architecture

### How data loads
```html
<script src="routes/routes.js"></script>  <!-- sets window.ROUTES_DATA = [...] -->
```
Uses `<script>` tag (not `fetch()`) so it works on `file://` protocol without a local server.

### Key globals in JavaScript
```javascript
const allRoutes   = window.ROUTES_DATA;   // array of route objects
const polylines   = [...];                // pre-built L.polyline for each route (same index)
let   heatLayer   = null;                 // current heatmap layer
let   routeOpacity = 0.6;
let   currentMapType = 'dark' | 'light';
```

### Filter logic
Filters work by **setting opacity to 0** on hidden polylines (not removing from map) — much faster than add/remove for 783 layers. Heatmap is rebuilt from filtered coords on each filter change (debounced at 120ms for sliders).

```javascript
// applyFilters() checks per route:
const show = okDate && okDist && okDay;
polylines[i].setStyle({ opacity: show ? routeOpacity : 0 });
// then rebuilds heatLayer from visible routes only
```

### UI Elements (IDs for future edits)

**Header:**
- `#sv-routes`, `#sv-km`, `#sv-pts`, `#sv-spd` — stat display values
- `#visible-count` — "X / 783 routes" filter counter
- `#btn-dark`, `#btn-light` — map type toggle buttons

**Filters panel (`#filters-panel`, left side):**
- `#date-from`, `#date-to` — date range inputs
- `#dist-min`, `#dist-max` — distance range sliders (0–39 km)
- `#dist-min-val`, `#dist-max-val` — displayed values
- `.day-cb` (×7) — day-of-week checkboxes, `value` = 0(Mon)…6(Sun)

**Controls panel (`#controls-panel`, right side):**
- `#chk-heat`, `#chk-routes` — layer visibility toggles
- `#sl-radius`, `#sl-blur` — heatmap appearance sliders
- `#sl-opacity` — route line opacity slider (0–100)

**Tooltip (`#tooltip`, top-left on hover):**
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
Hover highlight colour: `#ffffff` (both themes).

### Heatmap gradient
```javascript
{ 0.2: '#0000ff', 0.4: '#00ffff', 0.6: '#00ff00', 0.8: '#ffff00', 1.0: '#ff0000' }
```

### CSS theming
Body class `theme-dark` / `theme-light` controls all colours via CSS custom properties:
`--panel-bg`, `--panel-border`, `--label`, `--heading`, `--accent`, `--stat-bg`, `--divider`

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

## update_routes.py — Key Logic

```bash
# Regenerate routes.js from existing JSON files only:
python3 update_routes.py

# Import new routes from a HAR file (skips duplicates):
python3 update_routes.py --from-har export.har
```

Deduplication key: route `id` extracted from filename (`{date}_{id}.json` → split on `_`, take index 1).

---

## External Libraries (CDN, no install needed)

```html
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://unpkg.com/leaflet.heat@0.2.0/dist/leaflet-heat.js"></script>
```

No build tools, no npm, no server required. Open `journey_heatmap.html` directly in Chrome.

> **Note:** pip/npm installs are blocked in this environment (proxy restriction). All dependencies must be CDN-loaded or pure Python stdlib.
