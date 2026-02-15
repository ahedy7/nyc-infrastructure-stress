NYC Reliability & Resilience Stress Index
Primary question: Which NYC neighborhoods experience the highest infrastructure stress, and what systems (service demand, mobility reliability, utility reliability, climate exposure) are driving that stress?
Geography: 2020 NTAs (NTACode join key)
Time window: Rolling last 365 days (2025-02-15 → 2026-02-15)
Deliverables:

Deployed interactive dashboard (public URL)

GitHub repo w/ reproducible pipeline

Portfolio write-up page + screenshots

Features (Version A, locked):

svc_311_density = 311 requests per km² (rolling window)

mob_mta_delay_density = MTA delay incidents per km² (rolling window)

traf_congestion_proxy = share of road segments with mean speed < X mph (rolling window)

util_outage_density = outage complaints per km² (rolling window)

clim_flood_share = % of NTA area in FEMA flood hazard zone (static)

Index method:

Z-score each feature across NTAs

Stress score = mean of the 5 z-scores (equal weights)

Driver breakdown = per-feature z-scores for selected NTA

Robustness checks (must-have):

Alternate normalization: per km² vs raw counts (where applicable)

Alternate window: 180 days vs 365 days (only if feasible)

Optional: PCA weights for comparison (nice-to-have)

Dashboard must show:

Choropleth map of stress score by NTA

Sortable ranking table

Driver bar chart for selected NTA

Toggle: Baseline vs “Event Stress Week” (data-selected week)
