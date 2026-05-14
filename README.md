# NYC Infrastructure Stress Index

In this project, I built a tool to answer one question: where 
in New York City is infrastructure under the most stress, and 
which neighborhoods become disproportionately brittle compared 
to their own baseline during high-stress periods?

The answer serves different audiences differently. A city planner 
sees where to prioritize capital investment. A consultant sees 
where chronic underinvestment compounds over time. A technology 
company building city-scale products sees a neighborhood-level 
reliability signal for routing, demand forecasting, and urban 
simulation models. The methodology is applicable to infrastructure 
reliability analysis at any scale.

---

## Stage 1 — Data Collection

Four independent data sources were pulled from NYC Open Data and FEMA:

- **NYC 311 Service Requests** — filtered to infrastructure-relevant 
  complaint types including plumbing, electrical systems, water and 
  sewer drainage, street and roadway conditions, and related 
  infrastructure categories. Used as a proxy for chronic service 
  delivery strain across neighborhoods.
- **MTA Subway Delay Incidents** — captures mobility infrastructure 
  failure
- **Power Outage Complaints** — captures utility infrastructure failure
- **FEMA Flood Hazard Zone Boundaries** — captures structural climate 
  vulnerability

Each source represents a different dimension of infrastructure failure. 
No single source tells the full story. The index is designed to surface 
neighborhoods where multiple systems are failing simultaneously, which 
is what genuine infrastructure stress looks like.

DOT Traffic Speeds NBE was evaluated and excluded. The dataset is a 
real-time telemetry feed (106M rows, sub-minute updates) architecturally 
unsuited for annual NTA-level aggregation. MTA delay density serves as 
the primary mobility stress indicator.

---

## Stage 2 — Index Construction

All four features were spatially joined to NTA geography — New York 
City's 262 Neighborhood Tabulation Areas, the planning unit used by 
city agencies to allocate resources and report outcomes. Each feature 
was z-score standardized to put them on a common scale regardless of 
original units, then averaged with equal weights to produce a single 
baseline stress score per NTA.

Equal weights were chosen because no empirical basis exists for 
differential weighting without introducing arbitrary assumptions. The 
honest limitation is potential double counting between flood share and 
outage density. Flooding causes outages, which means climate 
vulnerability may carry slightly more implicit weight than its 25% 
share suggests.

The result: Fordham Heights and the South Bronx emerge as the most 
chronically stressed neighborhoods across all four dimensions 
simultaneously — a finding consistent with decades of documented 
underinvestment in those communities.

| Rank | NTA | Code | Baseline Score |
|------|-----|------|----------------|
| 1 | Fordham Heights | BX0503 | 3.48 |
| 2 | Mount Eden-Claremont West | BX0403 | 1.83 |
| 3 | Mount Hope | BX0502 | 1.79 |
| 4 | Highbridge | BX0402 | 1.77 |
| 5 | Harlem North | MN1002 | 1.65 |

---

## Stage 3 — Event Week Detection

Chronic stress rankings alone miss something important: some 
neighborhoods are always stressed, so a high score is normal for them. 
What matters for emergency preparedness and resilience investment is 
which neighborhoods become disproportionately worse during high-stress 
events relative to their own baseline.

To answer this I added an event week detection layer. Because the 
pipeline aggregated to annual totals, I used a parametric Monte Carlo 
bootstrap simulation — drawing 52 synthetic weekly samples from a 
normal distribution parameterized by each NTA's annual totals — to 
model plausible weekly stress variance. Weeks where combined citywide 
z-score exceeded 1.5 standard deviations were flagged as event weeks. 
I then computed a per-NTA delta: how much more or less stressed each 
neighborhood is during those weeks compared to its own annual baseline.

The finding: dense Manhattan commercial corridors like Midtown and FiDi 
have low chronic stress but high event deltas — low-baseline systems 
that fail hard under pressure. Crown Heights South shows compounding 
vulnerability — high baseline and high delta simultaneously, making it 
the highest priority for resilience investment.

| Rank | NTA | Code | Event Delta |
|------|-----|------|-------------|
| 1 | Midtown-Times Square | MN0502 | +3.04 |
| 2 | Midtown South-Flatiron-Union Square | MN0501 | +2.69 |
| 3 | Tribeca-Civic Center | MN0102 | +2.41 |
| 4 | Financial District-Battery Park City | MN0101 | +2.03 |
| 5 | Crown Heights South | BK0901 | +1.63 |

Note: event weeks are statistically simulated, not tied to real 
calendar dates. Weekly ETL from raw timestamped incident data is 
the documented next step for this project.

---

## Stage 4 — Dashboard and Deployment

A Plotly Dash app with a toggle between baseline stress and event 
week delta views, deployed on Render.

**Live dashboard: https://nyc-infrastructure-stress.onrender.com**

![Baseline Stress View](nyc-infrastructure-stress/arcgis_exports/screenshot_baseline.png)
![Event Week Delta View](nyc-infrastructure-stress/arcgis_exports/screenshot_delta.png)

---

## Limitations

- **311 reporting bias** — wealthier neighborhoods with higher civic 
  engagement may over-report relative to actual conditions, potentially 
  underestimating stress in lower-income areas
- **Monte Carlo simulation** — event weeks are statistically simulated, 
  not empirically observed from raw weekly data
- **Feature correlation** — equal weights assume independence; flood 
  share and outage density are correlated, introducing potential 
  implicit double-counting
- **FEMA map vintage** — flood zone boundaries may not reflect updated 
  post-Sandy exposure in some areas

---

## How to Reproduce

The processed data and NTA shapefile are included in the repo. 
To run the dashboard locally:

1. Clone the repo
2. `pip install -r requirements.txt`
3. `cd nyc-infrastructure-stress/dashboard && python app.py`
4. Open localhost:8050

To rebuild the index from raw data, update the date filters in 
each ETL script to your desired time window and re-run the pipeline 
in order. See `src/` for the full pipeline.

---

## Built By

Arvin Hedayat | Statistics, McGill University | 2026 | 
GitHub: [ahedy7](https://github.com/ahedy7)
