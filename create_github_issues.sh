#!/bin/bash
# Create GitHub issues for NYC Infrastructure Stress project
# Run: gh auth login   (if needed), then: ./create_github_issues.sh

REPO="ahedy7/nyc-infrastructure-stress"

# Milestone 1 — Pipeline Proof
gh issue create --repo "$REPO" --title "Export NTA boundaries (GeoJSON) from NYC Open Data" --body "Milestone 1 — Pipeline Proof"
gh issue create --repo "$REPO" --title "Lab: Aggregate 311 points → NTA (rolling 365d) export CSV" --body "Milestone 1 — Pipeline Proof"
gh issue create --repo "$REPO" --title "Build baseline feature table from ArcGIS exports" --body "Milestone 1 — Pipeline Proof"
gh issue create --repo "$REPO" --title "Compute baseline stress index + driver z-scores" --body "Milestone 1 — Pipeline Proof"
gh issue create --repo "$REPO" --title "Dash MVP: map + ranking + drivers" --body "Milestone 1 — Pipeline Proof"

# Milestone 2 — Add Remaining Systems
gh issue create --repo "$REPO" --title "Lab: Aggregate MTA delay incidents → NTA export CSV" --body "Milestone 2 — Add Remaining Systems"
gh issue create --repo "$REPO" --title "Lab: Aggregate DOT traffic speeds → NTA congestion proxy export CSV" --body "Milestone 2 — Add Remaining Systems"
gh issue create --repo "$REPO" --title "Lab: Aggregate outage complaints → NTA export CSV" --body "Milestone 2 — Add Remaining Systems"
gh issue create --repo "$REPO" --title "Lab: Flood zone overlay → NTA flood share export CSV" --body "Milestone 2 — Add Remaining Systems"

# Milestone 3 — Event Stress Test + Polish
gh issue create --repo "$REPO" --title "Detect event week from citywide spikes (delays/311)" --body "Milestone 3 — Event Stress Test + Polish"
gh issue create --repo "$REPO" --title "Compute event-week stress + delta vs baseline" --body "Milestone 3 — Event Stress Test + Polish"
gh issue create --repo "$REPO" --title "Dashboard toggle baseline/event + delta ranking" --body "Milestone 3 — Event Stress Test + Polish"
gh issue create --repo "$REPO" --title "README: consulting-style executive summary + screenshots" --body "Milestone 3 — Event Stress Test + Polish"
gh issue create --repo "$REPO" --title "Deploy Dash app on Render (free tier)" --body "Milestone 3 — Event Stress Test + Polish"

echo "Done! Created 15 issues."
