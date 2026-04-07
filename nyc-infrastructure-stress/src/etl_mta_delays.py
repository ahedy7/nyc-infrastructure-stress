"""
ETL: MTA subway delay-causing incidents -> NTA-level incident density.

Source: https://data.ny.gov/Transportation/MTA-Subway-Delay-Causing-Incidents-Beginning-2020/g937-7k7c

The Socrata table exposes monthly counts by subway line (no geocoded incidents).
We sum incidents in the requested window, then allocate each line's total to
2020 NTAs in proportion to MTA subway station locations that serve that line
(https://data.ny.gov/Transportation/MTA-Subway-Stations/39hk-dx4f).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests

DELAYS_URL = "https://data.ny.gov/resource/g937-7k7c.json"
STATIONS_URL = "https://data.ny.gov/resource/39hk-dx4f.json"
NTA_GEOJSON_URL = (
    "https://data.cityofnewyork.us/api/geospatial/9nt8-h7nd"
    "?method=export&format=GeoJSON"
)
PAGE_SIZE = 50_000


def _parse_month_value(raw: str) -> pd.Timestamp:
    return pd.to_datetime(raw, utc=True).tz_convert(None).normalize()


def fetch_delays(
    session: requests.Session,
    start_month: pd.Timestamp,
    end_month: pd.Timestamp,
) -> pd.DataFrame:
    """Paginate delay rows; filter by `month` (first day of calendar month)."""
    where = (
        f"month >= '{start_month.strftime('%Y-%m-%dT00:00:00.000')}' "
        f"and month <= '{end_month.strftime('%Y-%m-%dT00:00:00.000')}'"
    )
    offset = 0
    chunks: list[pd.DataFrame] = []
    while True:
        r = session.get(
            DELAYS_URL,
            params={
                "$where": where,
                "$order": "month",
                "$limit": PAGE_SIZE,
                "$offset": offset,
            },
            timeout=120,
        )
        r.raise_for_status()
        rows = r.json()
        if not rows:
            break
        chunks.append(pd.DataFrame(rows))
        if len(rows) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    if not chunks:
        return pd.DataFrame(columns=["month", "line", "incidents"])
    out = pd.concat(chunks, ignore_index=True)
    out["month"] = out["month"].map(_parse_month_value)
    out["incidents"] = pd.to_numeric(out["incidents"], errors="coerce").fillna(0).astype(int)
    return out


def fetch_stations(session: requests.Session) -> pd.DataFrame:
    r = session.get(STATIONS_URL, params={"$limit": 10_000}, timeout=120)
    r.raise_for_status()
    return pd.DataFrame(r.json())


def station_matches_line(line: str, row: pd.Series) -> bool:
    dr = (row.get("daytime_routes") or "").strip()
    name = row.get("stop_name") or ""
    tokens = str(dr).replace("-", " ").split()
    if line == "JZ":
        return "J" in tokens or "Z" in tokens
    if line == "S 42nd":
        return name in ("Times Sq-42 St", "Grand Central-42 St") and dr == "S"
    if line == "S Fkln":
        return name in ("Franklin Av", "Botanic Garden", "Park Pl") and dr == "S"
    if line == "S Rock":
        return name in (
            "Beach 105 St",
            "Beach 98 St",
            "Beach 90 St",
            "Rockaway Park-Beach 116 St",
            "Broad Channel",
        )
    return line in tokens


def ensure_nta_layer_path(nta_dir: Path) -> Path:
    """Return path to NTA boundaries (.shp or .geojson); download GeoJSON if missing."""
    nta_dir.mkdir(parents=True, exist_ok=True)
    preferred_shp = nta_dir / "geo_export.shp"
    if preferred_shp.exists():
        return preferred_shp
    shps = sorted(nta_dir.glob("*.shp"))
    if shps:
        return shps[0]
    preferred_geo = nta_dir / "geo_export.geojson"
    if preferred_geo.exists():
        return preferred_geo
    geos = sorted(nta_dir.glob("*.geojson"))
    if geos:
        return geos[0]
    r = requests.get(NTA_GEOJSON_URL, timeout=300)
    r.raise_for_status()
    preferred_geo.write_text(r.text, encoding="utf-8")
    return preferred_geo


def allocate_incidents_to_ntas(
    line_totals: pd.Series,
    stations: pd.DataFrame,
    nta: gpd.GeoDataFrame,
) -> pd.Series:
    """Return incident_count indexed by NTA code (nta2020)."""
    nta_ids = nta["nta2020"].astype(str).unique()
    counts = pd.Series(0.0, index=pd.Index(nta_ids))

    stations_gdf = gpd.GeoDataFrame(
        stations,
        geometry=gpd.points_from_xy(
            pd.to_numeric(stations["gtfs_longitude"], errors="coerce"),
            pd.to_numeric(stations["gtfs_latitude"], errors="coerce"),
        ),
        crs="EPSG:4326",
    )
    stations_gdf = stations_gdf[stations_gdf.geometry.notna()]

    nta_wgs = nta[["nta2020", "geometry"]].copy()
    joined = gpd.sjoin(
        stations_gdf,
        nta_wgs,
        how="left",
        predicate="intersects",
    )
    joined = joined[~joined.index.duplicated(keep="first")]
    if "nta2020" not in joined.columns:
        raise RuntimeError("Unexpected sjoin columns: " + repr(joined.columns.tolist()))

    for line, total in line_totals.items():
        mask = stations.apply(lambda row: station_matches_line(str(line), row), axis=1)
        sub = joined.loc[mask]
        if sub.empty:
            print(f"Warning: no stations matched for delay line {line!r}; skipping.", file=sys.stderr)
            continue
        sub = sub[sub["nta2020"].notna()]
        if sub.empty:
            print(f"Warning: stations for line {line!r} not in any NTA; skipping.", file=sys.stderr)
            continue
        vc = sub["nta2020"].astype(str).value_counts()
        weights = vc / vc.sum()
        for nta_code, w in weights.items():
            counts.loc[nta_code] = counts.loc[nta_code] + float(total) * float(w)

    return counts


def build_output_table(
    nta: gpd.GeoDataFrame,
    incident_by_nta: pd.Series,
) -> pd.DataFrame:
    """All NTAs with incident_count (0 for none), area_km2, density."""
    nta = nta.copy()
    nta["nta2020"] = nta["nta2020"].astype(str)
    nta_m = nta.to_crs(32618)
    nta["area_km2"] = nta_m.geometry.area / 1_000_000.0

    inc = incident_by_nta.reindex(nta["nta2020"]).fillna(0.0)
    inc = inc.astype(float)

    out = pd.DataFrame(
        {
            "NTACode": nta["nta2020"].values,
            "NTAName": nta["ntaname"].values,
            "incident_count": inc.values,
            "area_km2": nta["area_km2"].values,
        }
    )
    out["mob_mta_delay_density"] = out["incident_count"] / out["area_km2"].replace(0, float("nan"))
    out["mob_mta_delay_density"] = out["mob_mta_delay_density"].fillna(0.0)
    return out


def main(argv: list[str] | None = None) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    default_out = repo_root / "data_processed" / "nta_mta_delays.csv"
    default_nta_dir = repo_root / "data_raw" / "nta_2020"

    parser = argparse.ArgumentParser(description="MTA delays -> NTA CSV")
    parser.add_argument(
        "--output",
        type=Path,
        default=default_out,
        help=f"Output CSV path (default: {default_out})",
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default="2025-02-15",
        help="Window start (inclusive). Monthly rows are aligned to month starts.",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default="2026-02-15",
        help="Window end (inclusive).",
    )
    parser.add_argument(
        "--nta-dir",
        type=Path,
        default=default_nta_dir,
        help=(
            "Directory with 2020 NTA boundaries: prefer geo_export.shp; "
            "otherwise geo_export.geojson is downloaded from NYC Open Data."
        ),
    )
    args = parser.parse_args(argv)

    start = pd.Timestamp(args.start_date).normalize()
    end = pd.Timestamp(args.end_date).normalize()
    # Include months whose calendar month intersects [start, end].
    start_month = start.replace(day=1)
    end_month = end.replace(day=1)

    session = requests.Session()

    delays = fetch_delays(session, start_month, end_month)
    total_incidents = int(delays["incidents"].sum()) if len(delays) else 0

    line_totals = delays.groupby("line", dropna=False)["incidents"].sum()

    stations = fetch_stations(session)
    nta_path = ensure_nta_layer_path(args.nta_dir)
    nta = gpd.read_file(nta_path)
    if nta.crs is None:
        nta.set_crs("EPSG:4326", inplace=True)
    else:
        nta = nta.to_crs("EPSG:4326")

    incident_by_nta = allocate_incidents_to_ntas(line_totals, stations, nta)
    out = build_output_table(nta, incident_by_nta)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.output, index=False)

    nta_with = int((out["incident_count"] > 0).sum())
    pos = out[out["incident_count"] > 0]["mob_mta_delay_density"]
    dmin = float(pos.min()) if len(pos) else float("nan")
    dmax = float(pos.max()) if len(pos) else float("nan")

    print("Summary")
    print(f"  Total incidents fetched (sum of rows): {total_incidents}")
    print(f"  NTAs with incident_count > 0: {nta_with}")
    print(f"  Min mob_mta_delay_density (among NTAs with incidents): {dmin:.6g}")
    print(f"  Max mob_mta_delay_density (among NTAs with incidents): {dmax:.6g}")
    print(f"  Wrote: {args.output}")


if __name__ == "__main__":
    main()
