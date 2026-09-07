# Asset Health Index & DGA Analysis System

A React (Vite) + Flask application over the existing `CEB_TRANSMISSION` SQL Server
database. It implements the four specification documents in this folder:

| Spec | Implemented in |
|---|---|
| `HealthIndex_Automation_Spec.md` | `backend/core/{scoring,readers,hi_engine}.py` |
| `DGA_SYSTEM_SPEC.md` | `backend/core/dga_trend.py` |
| `PENTAGON_LOGIC.md` | `backend/core/pentagon.py` |
| `DGA_AI_DUVAL_LOGIC.md` | `backend/core/{duval,ml}.py` |

**Nothing is written back to the database.** Every health index is computed on
demand from the existing test tables.

---

## Quick start

```bat
setup.bat     :: once - installs Python and Node packages, checks the DB
start.bat     :: launches the API and the UI
```

Then open <http://127.0.0.1:5180>.

| Service | URL | Database |
|---|---|---|
| UI (Vite) | http://127.0.0.1:5180 | — |
| API (Flask) | http://127.0.0.1:5000 | `CEB_TRANSMISSION` (read-only) |
| Configuration service (Flask) | http://127.0.0.1:5001 | `config-service/config_store.db` (SQLite) |
| Daily snapshot job | Task Scheduler, 08:00 | `backend/snapshots/hi_snapshots.db` (SQLite) |

Port 5180 is used because Vite's default 5173 is already taken on this machine.

### Manual start

```bat
cd config-service && py app.py
cd backend        && py app.py
cd frontend       && npm run dev
```

The configuration service is optional infrastructure: if it is not running the
system still scores the whole fleet using the values held in
`CEB_TRANSMISSION`, and the Configuration screen says so rather than failing.

---

## Configuration

Connection settings come from the environment, optionally via `backend/.env`.
Windows integrated auth is the default and needs no secret.

```ini
HI_DB_SERVER=DESKTOP-E3R1QOH\SQLEXPRESS
HI_DB_NAME=CEB_TRANSMISSION
HI_DB_TRUSTED=1
```

For SQL Server authentication set `HI_DB_TRUSTED=0` plus `HI_DB_USER` /
`HI_DB_PASSWORD`. No password is ever stored in the repository.

---

## Sections

| Section | What it does |
|---|---|
| **Dashboard** | Fleet-wide asset counts, then health-index distribution, average, worst assets and scored table **scoped to transformers by default** — one click switches asset type |
| **Health Index** | Scored table, **transformers by default**, colour-coded by band, filterable, sortable and paged; drill into any asset |
| **Asset detail** | Component-by-component breakdown with measured value, score, weight, contribution, source table and test date; stored history |
| **Manual calculation** | Pick exactly which criteria to score on, enter the asset age and any manually assessed components, and see every value the database holds per criterion with the considered one highlighted |
| **Trend Analysis** | IEEE C57.104 trend score with per-gas table and full audit trail, gas concentration charts, **dual Duval pentagons**, **dual Duval triangles** |
| **DGA Status** | **IEEE C57.104-2019 Figure 2** status classification — Status 1/2/3 from gas levels (Tables 1 & 2), the change since the previous sample (Table 3) and the multi-point rate (Table 4), with the decision path, the gas-by-gas evidence, a fleet sweep, the reference tables and a printable report |
| **Duval Diagnosis** | Multi-method diagnosis: pentagons, triangles 1/4/5, IEEE limit tables, Rogers ratios, key gas, paper involvement, AI classifier, method agreement |
| **DGA Explorer** | Browse DGA history, chart arbitrary gas groups, rank the fleet by trend score |
| **Asset Register** | Inventory by type, substation and bay |
| **Test Availability** | Y/N matrix of which tests exist per asset, with record counts and last test date |
| **Configuration** | Edit score bands and component weights (saved to the configuration service), HI colour bands, engine flags, configuration health audit, change log |

---

## Colour system

The rule the whole palette follows: **colour that carries condition is reserved,
and nothing else may borrow it.**

| Layer | Colours | Job |
|---|---|---|
| **Chrome** — sidebar, header, page wash | Deep navy `#123252` → `#08172A`, page gradient `#EAF3FC` → `#F7FBFE` | Surfaces. Never encode data. |
| **Category accents** — inventory tiles, type chips, section headers | Power TR `#2A78D6` · Earthing `#4A3AA7` · OLTC `#D55181` · others muted blue-greys | Identity of an asset population. |
| **Condition** — HI badges, distribution bars, score chips | Green → blue → amber → orange → red, from `SCORE_VALUE` | Health only. |
| **Status** — warnings, config alerts | Amber / red | State only. |

The three transformer accents were validated as a categorical set against both
the white card and the tinted page, all pairs:

```
CVD separation      ΔE 13.0  (target ≥ 8)
Normal-vision floor ΔE 16.3  (floor ≥ 15)
Contrast vs surface all ≥ 3:1
```

They are deliberately drawn from blue/violet/rose and **never** from the
green–amber–red scale, so an inventory tile can never be misread as a health
verdict — a green "Earthing Transformers" tile would say "healthy" to anyone
scanning the page. Every tile and chip also carries an icon and a text label, so
colour is never the only cue.

Two mechanical traps worth remembering when editing this:

* `StatCard`/`SectionHeader` take a **hex** accent, typed as `` `#${string}` ``.
  A keyword like `accent="amber"` is not a valid CSS colour and would render as
  nothing; the type now rejects it at build time.
* Tailwind opacity steps must come from its scale. `bg-white/12` silently emits
  **no CSS** — use `/10` or `/20`.

---

## Asset categories and default scope

The dashboard and the health-index table open on **Power Transformers** — MT and
IBT units only. Earthing transformers and tap changers are separate populations
and are excluded from that default.

Two ideas are kept apart:

* **Scoring type** (`assetType`) selects the weights and score bands. Every
  transformer variant shares the `TR` configuration.
* **Category** (`category`) is the reporting grouping, and is what the type
  selector and all filtering use.

| Category | What it holds | Assets | Average HI |
|---|---|---|---|
| **TR** *(default)* | Power and inter-bus transformers (`MT*`, `IBT*`) | 278 | **77.4** |
| **AET** | Earthing and auxiliary transformers (`ET*`, `AT*`) | 264 | 66.3 |
| **OLTC** | On-load tap changers (`…/OLTC/…`, `…/OLTC1/…`, `…/OLTC2/…`) | 254 | 54.7 |
| CTVT ⚠ | Current and voltage transformers | 5,006 | bands mis-scaled |
| CB | Circuit breakers | 1,085 | 74.9 |
| ESDS ⚠ | Earth switches / disconnectors | 2,661 | no CR bands |
| SA ⚠ | Surge arresters | 3,520 | bands all zero |
| OTHER | Bare site codes, IEDs, voltage regulators, spares | 41 | — |
| All types | Everything | 13,109 | 72.2 |

Why the split matters: tap changers are scored on OLTC oil tests alone, so their
two criteria normalise to 100% of the weight between them and a bad oil BDV
drives the score straight to zero. Left in with the main fleet they monopolised
the "worst assets" list. Separated, the worst *power transformers* are visible —
and the transformer average rises from 67.9 to **77.4**, because it is no longer
dragged down by a different kind of asset.

`OTHER` exists so entries that are not really assets — bare site codes such as
`G001`, IEDs, spares — cannot inflate the transformer population.

The inventory tiles at the top of the dashboard stay fleet-wide: they describe
what exists, not what has been scored.

The API mirrors this. `/api/dashboard` and `/api/health-index` default to
`type=TR`, accept any category code, and take `type=all` for the whole fleet.

---

## Manual calculation

Open any asset from the Health Index table, then **Manual calculation**.

* **Criteria selection** — tick exactly the criteria to score on (DGA level, DGA
  trend, BDV, moisture, tan δ, and so on), or use *Select all* / *Clear*.
  Weights re-normalise over whatever you keep, so the index always lands on
  0–100 and the weight column is shown so the arithmetic is checkable.
* **Values from database** — every value the database holds for a criterion is
  listed, comma separated, with the one actually scored highlighted in solid
  blue. Hover any value for its source table, phase or tap, and test date.
  Oil BDV, moisture and insulation resistance are each recorded by more than one
  test, so this is where the *"which number did it use, and why"* question is
  answered. A criterion whose value is a blend rather than a pick — DGA level
  and DGA trend combine every gas — is badged **blended** and highlights nothing,
  because singling one gas out would misrepresent it.
* **Per-criterion columns** — score, normalised weight, and the sub-HI
  contribution (`weight × score`), with the health index as the column total.
* **Age** — entered by hand, overriding the database. Most assets have no
  commissioning year on record, so this is usually the only way to score age.
* **Manual components** — components with no test table at all (SFRA, partial
  discharge, visual condition, …) take a 0–1 score inline.

---

## How the health index works

```
HI = Σ ( normalisedWeight[c] × score[c] )
```

* Component scores run **0..1 with 1 healthy**; weights sum to 100, so the index
  lands on **0..100 where higher is better**.
* Weights are re-normalised over only the components that actually have data:
  `weight[c] = w[c] / Σw(available) × Σw(all)`.
* A component with no qualifying record is **excluded from normalisation**, not
  scored zero — a missing test never counts as a bad result.

Both the polarity and the normalisation were confirmed against the stored
`HEALTH_INDEX.LastScores` audit strings, which reproduce their own `Result`.

### Colour bands

| Band | Range |
|---|---|
| Very Good | 85 – 100 |
| Good | 70 – 85 |
| Fair | 55 – 70 |
| Poor | 40 – 55 |
| Very Poor | 0 – 40 |

---

## Daily snapshot job

Scoring one asset touches around twenty tables, so computing 13,109 assets on
every page load is not viable — a live sweep of just 60 assets takes ~1.8 s. A
scheduled job runs once a day and stores one row per asset; the dashboard and
health-index table then read those rows.

| | Live sweep | Daily snapshot |
|---|---|---|
| Dashboard, whole fleet | minutes | **34 ms** |
| Health-index page (200 rows) | ~6 s | **13 ms** |
| Full fleet computation | — | 197 s for 13,109 assets |

### Setting up the schedule

Run **once, as Administrator**:

```bat
schedule-daily-snapshot.bat
```

This registers a Task Scheduler entry named **HI Daily Snapshot** that runs
every day at 08:00. Windows has no cron; Task Scheduler is the equivalent.

```bat
schtasks /Run    /TN "HI Daily Snapshot"      :: run it now
schtasks /Query  /TN "HI Daily Snapshot" /V /FO LIST
schtasks /Delete /TN "HI Daily Snapshot" /F
```

The job writes to `backend/logs/snapshot.log` and does **not** need the API or
UI to be running — it talks to SQL Server itself, so the fleet is refreshed even
on a machine where nobody has opened the web app.

### Running it by hand

```bat
cd backend
py run_snapshot.py                 :: every scorable asset
py run_snapshot.py --types TR CB   :: only these asset types
py run_snapshot.py --limit 50      :: quick smoke run
```

### Storage

| Table | Holds |
|---|---|
| `asset_health` | One row per asset, upserted in place — always the latest picture |
| `snapshot_run` | Run log: start, finish, duration, counts, trigger, any error |
| `dashboard_summary` | Precomputed counts, distribution and worst-asset list |

Only one sweep runs at a time; a second request is told the first is still going
rather than being queued behind it. A failure on one asset is logged and the
sweep continues.

### In the app

Every screen backed by the snapshot shows a bar saying where the numbers came
from and how old they are, with **Recalculate now**, which runs the sweep in the
background with a progress bar — the app stays usable meanwhile. If the snapshot
is more than 36 hours old the bar turns amber and says the 08:00 job may not have
run. With no snapshot at all the dashboard falls back to a live sample and says
so.

Fresh numbers on demand, without waiting for a fleet sweep:

* **Asset detail** — one asset is always computed live.
* **Manual calculation** — always live, and never touches the snapshot.
* `POST /api/snapshot/asset/<asset>` — recompute one asset (~47 ms) and update
  its stored row.

Set `HI_SNAPSHOT_TOKEN` if the API is reachable beyond localhost; the trigger
endpoint then requires an `X-Snapshot-Token` header.

---

## Configuration microservice

Score ranges and component weights are editable from the Configuration screen
and are stored by a **separate service with its own database**, so the plant
system is never written to.

```
config-service/
  app.py             Flask service on port 5001
  store.py           SQLite schema and access
  config_store.db    created on first run
```

| Table | Holds |
|---|---|
| `band_override` | A replacement range table, keyed by asset type + band name |
| `weight_override` | Replacement component weights, keyed by asset type |
| `change_log` | Append-only history: who changed what, when, before and after |

An override **replaces a band table wholesale** rather than patching individual
rows, so a saved table is exactly what the engineer reviewed — there is no silent
blending of old and new thresholds. Descending tables (BDV, IFT, IR, PD) are
edited exactly as stored, upper edge first, to match what the source system
shows.

Edits take effect on the next calculation; the API clears its caches on save.
The revert arrow on any edited table discards the override and returns to the
source values. Validation rejects empty ranges and non-numeric scores.

**Environment**

| Variable | Default |
|---|---|
| `CFG_PORT` / `CFG_HOST` | `5001` / `127.0.0.1` |
| `CFG_DB_PATH` | `config-service/config_store.db` |
| `HI_CONFIG_SERVICE_URL` | `http://127.0.0.1:5001` (read by the main API) |

The browser never talks to this service directly — the main API proxies writes,
so there is one origin and the service need not be exposed.

---

## Known data issues surfaced by the UI

The app reports these rather than hiding them.

### 1. Score bands are only complete for TR and CB

`SCORE_VALUE` in the live database is not fully configured:

| Asset type | Status |
|---|---|
| Power Transformer | OK — 22/22 band tables usable |
| Circuit Breaker | OK — 5/5 usable |
| CT / VT | **Partial** — `IR#CTVT` and `TAND#CTVT` score 0.01–0.05 where the convention is 0–1; they look mis-scaled by a factor of ~20 |
| ES / DS | **Partial** — `CR#ESDS` has no bands |
| Surge Arrester | **Unconfigured** — all bands score 0 |
| Capacitor Bank | **Unconfigured** — no bands |

Affected assets therefore score near zero, which looks like a condemned asset but
is really an empty configuration table. The system flags them, excludes them from
the fleet average, and shows exactly which band tables are at fault on the
Configuration screen. Fixing the rows in `SCORE_VALUE` is all that is needed —
the engine picks new bands up on the next refresh.

### 2. Asset age comes from the CMMS, not from the HI database

`CEB_ASSET` is empty and `SFRA_HEADER.ManufactureYear` covers 165 assets, so AGE
used to be unscoreable almost everywhere. It is now read from the Tomms CMMS by
the method in [`ASSET_ATTRIBUTES_INTEGRATION.md`](./ASSET_ATTRIBUTES_INTEGRATION.md):
the field is `ast_det.ast_det_datetime1`, labelled **"Year of Manufacture(G)"** in
`cf_label`, joined `ast_det.mst_RowID = ast_mst.RowID`. That covers **9,065 of
the 13,109 scored assets**.

Three things the source demands and `core/attributes.py` does:

* **The junk is filtered.** 1900/1905 are placeholders and 2102/2103/2180 are
  typos; 41 fleet assets carry one. They read as "no year", never as a
  126-year-old asset.
* **The label is asserted, not assumed.** The column number means nothing on its
  own — an administrator can re-purpose the UDF slot from inside the CMMS. The
  caption is checked against `cf_label` and reported on `/api/health`.
* **The bulk pull never happens in a request.** `ast_det` is an unindexed heap:
  one asset is ~0.1 s, the whole fleet ~4 minutes. The daily snapshot job primes
  a disk-cached map; live pages use the per-asset lookup.

Sources rank: engineer-entered age → CMMS → `CEB_ASSET` → `SFRA_HEADER`. Every
source that had a year stays visible as a candidate with the reason it lost, so
the 15 assets where SFRA and the CMMS disagree show the disagreement rather than
hiding it. Where no source has a usable year, AGE is dropped from normalisation
rather than scored zero, and the UI still exposes the manual override.

Tests: `python -m pytest backend/tests` (add `-m "not live"` off the plant
network).

### 3. The C57.104-2019 tables were reconstructed from a scan

The DGA Status section's decision logic is exact — it is the Figure 2 flowchart
implemented literally, and the section 8 known-answer vector from
`DGA_Status_Logic_C57104-2019.md` is asserted in `tests/test_dga_status.py`.
The **numeric tables** are the weak part: they were reconstructed from a scanned
copy of the standard, and a handful of cells were merged or faint.

Those cells are flagged rather than hidden. A limit that came from an ambiguous
cell is marked `‡` in the evidence table, listed in the report's caveats, and
carried on every trigger it produced. One cell — **Table 3, C2H4, in the O₂/N₂
> 0.2 section** — could not be read at all: it is `None`, that one comparison is
skipped, and every affected result says so in its assumptions rather than
guessing a number.

Verify the flagged cells against an authoritative copy of IEEE C57.104-2019
§6.1.3 before the section is used for real decisions. The tables live in one
place, `backend/core/dga_status.py`, as `TABLE1`–`TABLE4`.

### 4. Duval Triangle 1 polygons were rebuilt

The vertex list in `DGA_AI_DUVAL_LOGIC.md` §4.2 cannot be drawn as written —
several vertices do not sum to 100 % (`T1 (0,0,4)`, `(98,0,0)`, `(0,0,0)`;
`T2 (0,20,4)`, `(0,50,0)`; `T3 (0,50,0)`; `DT (0,0,4)`), and because
`ternary_to_cartesian` normalises its inputs, `(0,0,4)` lands on the C₂H₂ apex
while `(0,0,0)` has no defined position at all. Rendered verbatim, four of seven
zones come out as wrong, partly self-intersecting shapes.

The zones are therefore derived from the threshold lines the spec states in its
own §3.2 rule ladder (CH₄=98, C₂H₂=4/13/15, C₂H₄=20/23/50). Every vertex sums to
100 and the seven zones tile the triangle exactly once, verified over a grid with
zero overlaps.

Classification uses point-in-polygon on those same polygons, so **the chart and
the verdict can never disagree**. The legacy rule ladder still runs alongside and
the UI reports where the two differ — the spec's own documented edge case
(`200,80,20,150,90`) reproduces exactly: polygon says `D2`, ladder says `DT`.

### 5. Duval Triangles 4 and 5 are provisional

Neither is specified in your documents. They are included for the dual-triangle
view using the published Duval method and are **badged "Provisional"** in the UI
pending engineering sign-off against your reference charts.

---

## Engine behaviour flags

Each corresponds to a documented discrepancy in
`HealthIndex_Automation_Spec.md` §9. The default implements the intended reading;
set the environment variable to `0` to restore the literal legacy behaviour.

| Variable | Default behaviour |
|---|---|
| `HI_DGA_PER_GAS_OWN_FIELD` | Each gas is banded against its own column, not `H2ppm` |
| `HI_DIRANA_SCORE_OWN_VALUE` | DIRANA bands the moisture value, not the tan-δ value |
| `HI_AIO_IFTO_UNCROSSED` | Acidity reads `TRANS_ACIDITY`, IFT reads `TRANS_ITO` |
| `HI_SA_IR_USES_IR_FIELD` | SA insulation resistance reads `InsulationResistanceHVEGOhm`, not `CounterReading` |
| `HI_OLTC_USES_CEB_OLTC` | OLTC oil tests read `CEB_OLTC`, not `CEB_OUT_CT` |
| `HI_EC_BAND_ASCENDING` | Exciting current bands the larger deviation deterministically |

The live database confirmed several of these: `CEB_OLTC` exists as a real table
(876 rows), and `CEB_SA.InsulationResistanceHVEGOhm` is populated on ~63 % of
rows, so both spec items are indeed source defects.

---

## AI fault classifier

An XGBoost classifier trained on the three DGA datasets in the project root.
**Applies to power transformers with DGA data only** — it learns from transformer
oil gas concentrations, so it is refused for any other asset type rather than
returning a meaningless number. Every other diagnostic method (IEEE limits,
Rogers, Duval triangles and pentagons) works with or without it.

### Training

```bat
cd backend
py train_model.py                    :: train and save weights
py train_model.py --strategy merge   :: alternative label handling (below)
py train_model.py --report           :: print the saved model card
```

Weights are written to `backend/ml_models/`:

| File | Contents |
|---|---|
| `dga_fault_model.pkl` | The trained XGBoost booster |
| `dga_label_encoder.pkl` | Class-label encoding |
| `model_card.json` | Data, decisions, scores and feature importances behind these weights |

The API loads the saved weights at startup, trains from the datasets if none
exist, and keeps the model in memory — retraining per request would stall every
analysis by seconds. *Train / retrain* on the Configuration screen and
`POST /api/ml/train` do the same thing.

### Results

| | |
|---|---|
| Training rows | 2,457 (from 3,147 merged) |
| Fault classes | 7 |
| **5-fold CV accuracy** | **84.25% ± 2.05** |
| Hold-out accuracy | 83.54% (492 samples) |

Per class: Normal 0.94 F1 · High-temperature overheating 0.90 · Low-temperature
overheating 0.80 · Partial discharge 0.77 · Arc discharge 0.75 ·
Middle-temperature overheating 0.74 · Spark discharge 0.73.

The two weakest classes are the ones that genuinely overlap in gas space —
Middle-temperature overheating against its neighbours, and Spark against Arc
discharge. Confidence is reported with every prediction and flagged
green / amber / red at 85% and 65%, so a borderline call is visible as one.

Most influential features: `pct_C2H2` (acetylene fraction — the arcing gas),
`TDCG` (total combustible gas, a severity scalar), `R4_C2H2_CH4`, `log_C2H4`.

### Two things the merged data needed

Both are recorded in the model card and shown on the Configuration screen.

**668 duplicate rows dropped.** 21% of the merged set was exact duplicates.
Left in, the same row lands in both the training and test split, and the
reported accuracy measures memorisation. Measured: **88.48% with duplicates vs
83.54% without — 4.94 points of pure leakage.** The lower figure is the real one.

**A label granularity clash.** Two sources carry the coarse class
`Low/Middle-temperature overheating` (22 rows) while all three also carry the
finer `Low-temperature` (248) and `Middle-temperature` (202). Those classes are
not disjoint — a sample cannot be in both. The default (`--strategy drop`)
discards the 22 coarse rows, preserving the Low-versus-Middle distinction, which
is Duval T1 (<300 °C) against T2 (300–700 °C) where T2 implies paper
carbonisation. `--strategy merge` folds the fine classes into the coarse one
instead: six classes, no rows lost, no T1/T2 distinction. Set
`HI_ML_COARSE_LABEL` to change the default.

The 19-feature vector and hyperparameters follow `DGA_AI_DUVAL_LOGIC.md` §2
exactly.

### Requirements

`pandas`, `numpy`, `scikit-learn`, `xgboost`, `joblib`, `openpyxl` — install with
`py -m pip install -r backend\requirements-ml.txt`.

---

## API reference

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | API, database and ML status |
| `GET /api/assets` | Asset list; `type`, `site`, `q`, `limit` |
| `GET /api/assets/counts` | Dashboard tile counts |
| `GET /api/assets/sites` | Substation rollup |
| `GET /api/dashboard` | Counts, distribution, scored rows, config audit |
| `GET /api/health-index` | Scored table; `type`, `site`, `limit`, `offset` |
| `GET /api/health-index/<asset>` | Full component breakdown |
| `POST /api/health-index/<asset>` | Recompute with `{selected, manual, age}` |
| `PUT /api/config/bands/<type>/<band>` | Save a range table |
| `DELETE /api/config/bands/<type>/<band>` | Revert to the source range table |
| `PUT /api/config/weights/<type>` | Save component weights |
| `DELETE /api/config/weights/<type>` | Revert to the source weights |
| `GET /api/config/history` | Configuration change log |
| `GET /api/snapshot/status` | Last run, age, staleness, progress |
| `GET /api/snapshot/history` | Snapshot run log |
| `POST /api/snapshot/run` | Start a fleet sweep (background by default) |
| `POST /api/snapshot/asset/<asset>` | Recompute one asset and update its row |
| `GET /api/dga/assets` | Assets with DGA history |
| `GET /api/dga/trend/<asset>` | IEEE C57.104 trend score and audit trail |
| `POST /api/dga/trend/fleet` | Fleet trend ranking, worst first |
| `GET /api/dga/series/<asset>` | Chart-ready gas series; `gases` |
| `GET /api/dga/status/<asset>` | IEEE C57.104-2019 Figure 2 status, evidence and triggers |
| `GET /api/dga/status/report/<asset>` | Full status report payload for one asset |
| `POST /api/dga/status/fleet` | Fleet status sweep, worst first, with counts by status |
| `GET /api/dga/status/tables` | The four C57.104-2019 reference tables |
| `GET /api/duval/geometry` | Pentagon and triangle drawing geometry |
| `GET,POST /api/duval/analyse` | Full multi-method diagnosis |
| `GET /api/availability` | Test availability matrix |
| `GET /api/config` | Bands, weights, flags, configuration audit |
| `GET /api/ml/status` | Model card: scores, classes, data provenance |
| `POST /api/ml/train` | Retrain and save weights |
| `POST /api/ml/predict` | Classify a gas sample (transformers only) |

---

## Verified behaviour

* **Pentagon** reproduces the `PENTAGON_LOGIC.md` §12 regression exactly —
  centroid `(-2.809, -2.309)`, zones `T1` / `O`.
* **Duval Triangle 1** passes every validation case in `DGA_AI_DUVAL_LOGIC.md`
  §10, including the documented ladder-vs-polygon edge case.
* **Health index** reproduces the weight normalisation stored in
  `HEALTH_INDEX.LastScores`.
* Live fleet: 13,109 assets across 88 substations — 835 transformers, 3,277 CT,
  1,650 VT, 3,522 surge arresters, 1,085 breakers, 2,661 ES/DS.

---

## Project layout

```
backend/
  app.py              Flask routes
  config.py           environment configuration and ODBC driver selection
  db.py               SQL Server access, JSON coercion, TTL cache
  core/
    assets.py         asset inventory derived from asset numbering
    scoring.py        score bands, weights, normalisation, config audit
    readers.py        one measurement reader per component
    hi_engine.py      health index assembly
    dga_trend.py      IEEE C57.104 trend scoring (the 0-1 health-index number)
    dga_status.py     IEEE C57.104-2019 Figure 2 status classification and report
    pentagon.py       Duval dual pentagon geometry and diagnosis
    duval.py          triangles, IEEE tables, Rogers, key gas
    ml.py             optional XGBoost classifier
frontend/
  src/
    api.ts            fetch helper with request cancellation
    components/       layout, shared UI primitives
    charts/           dual pentagon, triangles, Recharts wrappers
    pages/            one file per section
```
