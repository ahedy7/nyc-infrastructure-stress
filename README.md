## NYC Infrastructure Stress Index

The NYC Infrastructure Stress Index is a neighborhood-level composite that ranks infrastructure pressure across service demand, mobility disruption, utility reliability, and flood exposure. It is built for city planners, infrastructure analysts, and resilience teams at agencies and consultancies such as AECOM, Arup, and NYC government partners. The index supports capital investment prioritization, emergency preparedness planning, and targeted resilience interventions by identifying where chronic stress is concentrated and where systems become disproportionately brittle under high-stress conditions. Results are delivered at the NTA scale so planners can compare neighborhoods, rank risk, and align spending with measurable stress signals.

## Question

Where in New York City is infrastructure under the most stress, and which neighborhoods become disproportionately brittle during high-stress events?

## Data Sources

| Feature | Source | Metric |
|---|---|---|
| 311 Service Requests | NYC Open Data | Complaint density per km² |
| MTA Delay Incidents | MTA / NYC Open Data | Incident density per km² |
| Power Outage Complaints | NYC Open Data 311 | Complaint density per km² |
| FEMA Flood Hazard Zones | FEMA NFHL | Share of NTA area in flood zone |

DOT Traffic Speeds NBE was evaluated and excluded. The dataset is a real-time telemetry feed (106M rows, sub-minute updates) architecturally unsuited for annual NTA-level aggregation. MTA delay density serves as the primary mobility stress indicator.

## Methodology

Neighborhood Tabulation Areas (NTAs) are the geographic unit of analysis. NTAs are the standard NYC planning geography, with 262 NTAs citywide. They are granular enough to surface neighborhood inequality, stable enough for reliable density metrics, and directly actionable for capital planning and emergency operations.

Each feature is z-score standardized across all NTAs. The index applies equal weights (25% per feature). The baseline stress score is the mean of the four z-scores. Equal weighting is used because there is no empirical basis for differential weighting without introducing arbitrary assumptions.

Event week delta is estimated with Monte Carlo simulation over annual aggregates to detect anomalous stress weeks. Event weeks are statistically plausible stress windows, not tied to real calendar dates. A positive delta indicates a neighborhood becomes brittle during events. A negative delta indicates relative resilience during events.

Limitations include 311 reporting bias, with wealthier neighborhoods more likely to over-report. The event window uses a Monte Carlo simulation approximation. Equal weights assume feature independence, but flood share and outage density are correlated and may implicitly double-count related risk. FEMA flood maps may not reflect post-Sandy updated flood risk in all areas.

## Findings

### Chronic Stress

Chronic infrastructure stress is concentrated in the South Bronx and Upper Harlem. These neighborhoods show persistent service delivery failures across all four dimensions.

| Rank | NTA | Code | Baseline stress score |
|---|---|---|---|
| 1 | Fordham Heights | BX0503 | 3.48 |
| 2 | Mount Eden-Claremont West | BX0403 | 1.83 |
| 3 | Mount Hope | BX0502 | 1.79 |
| 4 | Highbridge | BX0402 | 1.77 |
| 5 | Harlem North | MN1002 | 1.65 |

### Event Week Brittleness

During high-stress event weeks, dense Manhattan commercial corridors show the highest delta. These are low-baseline systems that fail disproportionately under pressure.

| Rank | NTA | Code | Event delta |
|---|---|---|---|
| 1 | Midtown-Times Square | MN0502 | +3.04 |
| 2 | Midtown South-Flatiron-Union Square | MN0501 | +2.69 |
| 3 | Tribeca-Civic Center | MN0102 | +2.41 |
| 4 | Financial District-Battery Park City | MN0101 | +2.03 |
| 5 | Crown Heights South | BK0901 | +1.63 |

### Compounding Vulnerability

Crown Heights South appears in both rankings, with elevated chronic baseline stress and elevated event delta. This pattern defines compounding vulnerability: structural fragility that is amplified during stress events. Neighborhoods in this category should be treated as the highest priority for resilience investment.

## How to Reproduce

Run these steps from the `nyc-infrastructure-stress` directory.

1. Clone repo
2. `pip install -r requirements.txt`
3. Download NTA shapefile to `data_raw/nta_2020/`
4. Run scripts in order:
   - `src/etl_311.py`
   - `src/etl_mta_delays.py`
   - `src/etl_outages.py`
   - `src/etl_flood_zones.py`
   - `src/compute_index.py`
   - `src/build_event_window.py`
5. `cd dashboard && python app.py`
6. Open `localhost:8050`

## Dashboard

Live dashboard available at [RENDER URL]

<img width="1712" height="480" alt="image" src="https://github.com/user-attachments/assets/4f929f54-edaa-4de2-b1be-4519e1a0e953" />

<img width="1694" height="479" alt="image" src="https://github.com/user-attachments/assets/6547b94d-52be-4ad0-bcf7-eebf00577a7d" />


## Built By

Arvin Hedy | Statistics, McGill University | 2026  
GitHub: ahedy7
