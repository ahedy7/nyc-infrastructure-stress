# NYC Reliability & Resilience Stress Index

**Primary question:** Which NYC neighborhoods experience the highest infrastructure stress, and what systems (service demand, mobility reliability, utility reliability, climate exposure) are driving that stress?

**Live dashboard:** <link>  
**Portfolio write-up:** <link>  
**Repo:** <link>


## Project specs

| Item | Value |
|---|---|
| Geography | 2020 NTAs (join key: `NTACode`) |
| Time window | Rolling last 365 days (2025-02-15 → 2026-02-15) |
| Unit | per km² (where applicable) |
| Index | mean of 5 z-scores (equal weights) |


## Deliverables

- [ ] Deployed interactive dashboard (public URL)
- [ ] GitHub repo with reproducible pipeline
- [ ] Portfolio write-up page + screenshots


## Features (Version A — locked)

| Feature | Definition | Window | Type |
|---|---|---:|---|
| `svc_311_density` | 311 requests per km² | rolling | dynamic |
| `mob_mta_delay_density` | MTA delay incidents per km² | rolling | dynamic |
| `traf_congestion_proxy` | Share of road segments with mean speed < 10 mph | rolling | dynamic |
| `util_outage_density` | Outage complaints per km² | rolling | dynamic |
| `clim_flood_share` | % of NTA area in FEMA flood hazard zone | — | static |

> **Note:** Replace **X mph** with the actual threshold and briefly justify it (1 sentence).


## Index method

1. Compute each feature per NTA.
2. Z-score each feature **across NTAs**.
3. **Stress score** = mean of the 5 z-scores (equal weights).
4. **Driver breakdown** = per-feature z-scores for a selected NTA.


## Robustness checks (must-have)

- [ ] Sensitivity to winsorization / clipping extreme values  
- [ ] Alternative weighting (e.g., equal vs. PCA-based vs. domain weights)  
- [ ] Correlation check (features not redundant)  
- [ ] Stability over time (rank churn month-to-month)  


## Data sources (fill in)

- 311: [https://data.cityofnewyork.us/Social-Services/311-Service-Requests-from-2020-to-Present/erm2-nwe9/about_data](url)
- MTA delays: [https://data.ny.gov/Transportation/MTA-Subway-Delay-Causing-Incidents-Beginning-2020/g937-7k7c/about_data](url)
- Road speeds / segments: [https://data.cityofnewyork.us/Transportation/DOT-Traffic-Speeds-NBE/i4gi-tjb9/about_data](url)
- Utility outages: [https://data.cityofnewyork.us/Social-Services/power-outage-complaints/br6j-yp22/about_data](url)
- FEMA flood hazard zones: [https://www.fema.gov/flood-maps/national-flood-hazard-layer?utm_source=chatgpt.com](url) , [https://opdgig.dos.ny.gov/datasets/fema-flood-hazard-zones/about?utm_source=chatgpt.com](url)


## Repo structure

```txt
/etl
/model
/dashboard
/notebooks
/data (gitignored)
/docs
