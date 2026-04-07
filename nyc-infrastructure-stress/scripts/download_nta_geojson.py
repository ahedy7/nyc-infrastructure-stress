#!/usr/bin/env python3
"""
Download NYC 2020 NTA GeoJSON from NYC Open Data.
Run from project root: python scripts/download_nta_geojson.py
Saves to: 2020_Neighborhood_Tabulation_Areas_(NTAs)_20260303.geojson
"""
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = PROJECT_ROOT / "2020_Neighborhood_Tabulation_Areas_(NTAs)_20260303.geojson"
URL = "https://data.cityofnewyork.us/api/geospatial/4hft-v355?method=export&format=GeoJSON"

def main():
    print(f"Downloading from {URL}...")
    try:
        req = urllib.request.Request(URL, headers={"User-Agent": "NYC-Infrastructure-Stress/1.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
    except Exception as e:
        print(f"Download failed: {e}")
        print("\nManual download: Visit https://data.cityofnewyork.us/d/4hft-v355")
        print("  Click 'Export' -> 'GeoJSON' and save to project root.")
        return 1
    if len(data) < 1000:
        print("Download returned insufficient data. Try manual download.")
        return 1
    OUT_PATH.write_bytes(data)
    print(f"Saved to {OUT_PATH} ({len(data):,} bytes)")
    return 0

if __name__ == "__main__":
    exit(main())
