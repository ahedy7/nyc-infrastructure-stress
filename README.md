# nyc-infrastructure-stress

NYC Infrastructure Stress Index — NTA-level composite of service demand, mobility stress, utility reliability, and flood exposure.

## Features (index inputs)

| Feature | Definition | Window | Type |
|---|---|---:|---|
| `svc_311_density` | 311 requests per km² | rolling | dynamic |
| `mob_mta_delay_density` | MTA delay incidents per km² | rolling | dynamic |
| `util_outage_density` | Outage complaints per km² | rolling | dynamic |
| `clim_flood_share` | % of NTA area in FEMA flood hazard zone | — | static |

Road speed data (DOT Traffic Speeds NBE) was evaluated and excluded. The dataset is a real-time telemetry feed (106M rows, sub-minute updates) architecturally unsuited for annual NTA-level aggregation. Transit delay density (`mob_mta_delay_density`) serves as the primary mobility stress indicator. This exclusion was a deliberate methodological decision — data quality over feature count.

## Method

- Geography: 2020 NTAs  
- Rolling window: last 365 days (see `PROJECT_BRIEF.md`)  
- **Stress score:** mean of **4** z-scores (equal weights), one per feature above  

## Dashboard

Run from `nyc-infrastructure-stress/` (see `run_dashboard.sh`).

## How to reproduce

1. Build `data_processed/baseline_features.csv` (includes columns named in `src/config.py` → `INDEX_FEATURES`).  
2. Run `python src/compute_index.py` → `data_processed/baseline_index.csv`.  
3. Launch the dashboard.

## Limitations

See `PROJECT_BRIEF.md` (robustness checks, data sources).
