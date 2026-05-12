"""
Build the NTA infrastructure stress index from processed feature tables.

The index combines four baseline features with equal weights (25% each):
311 service request density, MTA delay incident density, utility outage complaint
density, and FEMA flood-zone area share. Each feature is z-scored across NTAs,
and baseline_stress_score is the mean of those z-scores. Event-window brittleness
comes from nta_event_delta.csv, where event stress is derived from Monte Carlo
simulation of weekly MTA and outage loads during flagged citywide event weeks.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from config import INDEX_FEATURES, get_project_root

FEATURE_FILES: tuple[tuple[str, str], ...] = (
    ("nta_311_density.csv", "svc_311_density"),
    ("nta_mta_delays.csv", "mob_mta_delay_density"),
    ("nta_outages.csv", "util_outage_density"),
    ("nta_flood_zones.csv", "clim_flood_share"),
)

Z_COLUMNS: dict[str, str] = {
    "svc_311_density": "z_311",
    "mob_mta_delay_density": "z_mta",
    "util_outage_density": "z_outage",
    "clim_flood_share": "z_flood",
}

OUTPUT_COLUMNS: tuple[str, ...] = (
    "NTACode",
    "NTAName",
    "area_km2",
    "svc_311_density",
    "mob_mta_delay_density",
    "util_outage_density",
    "clim_flood_share",
    "z_311",
    "z_mta",
    "z_outage",
    "z_flood",
    "baseline_stress_score",
    "baseline_rank",
    "event_stress",
    "event_delta",
    "delta_rank",
)


def _zscore(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    mean = values.mean()
    std = values.std(ddof=0)
    if not pd.notna(std) or std == 0:
        return pd.Series(0.0, index=series.index, dtype=float)
    return (values - mean) / std


def _drop_duplicate_metadata(df: pd.DataFrame) -> pd.DataFrame:
    drop_cols = [
        col
        for col in df.columns
        if col.endswith("_y") and col[:-2] in {"NTAName", "area_km2"}
    ]
    if drop_cols:
        df = df.drop(columns=drop_cols)
    rename_cols = {
        col: col[:-2]
        for col in df.columns
        if col.endswith("_x") and col[:-2] in {"NTAName", "area_km2"}
    }
    if rename_cols:
        df = df.rename(columns=rename_cols)
    return df


def _warn_missing_features(df: pd.DataFrame, features: tuple[str, ...]) -> None:
    for feature in features:
        missing_mask = pd.to_numeric(df[feature], errors="coerce").isna()
        if not missing_mask.any():
            continue
        missing_ntas = df.loc[missing_mask, ["NTACode", "NTAName"]]
        print(
            f"WARNING: Filled missing {feature} with 0 for "
            f"{len(missing_ntas)} NTA(s):"
        )
        for _, row in missing_ntas.iterrows():
            print(f"  {row['NTACode']} - {row['NTAName']}")


def merge_feature_tables(data_dir: Path) -> tuple[pd.DataFrame, set[str]]:
    input_nta_codes: set[str] = set()
    base_name, _ = FEATURE_FILES[0]
    base_path = data_dir / base_name
    merged = pd.read_csv(base_path)
    if "NTACode" not in merged.columns:
        raise KeyError(f"{base_path} missing `NTACode`.")
    input_nta_codes.update(merged["NTACode"].astype(str))

    for file_name, feature in FEATURE_FILES[1:]:
        path = data_dir / file_name
        right = pd.read_csv(path)
        if "NTACode" not in right.columns:
            raise KeyError(f"{path} missing `NTACode`.")
        if feature not in right.columns:
            raise KeyError(f"{path} missing `{feature}`.")
        input_nta_codes.update(right["NTACode"].astype(str))
        merged = merged.merge(right, on="NTACode", how="left", suffixes=("", "_y"))
        merged = _drop_duplicate_metadata(merged)

    for feature in INDEX_FEATURES:
        if feature not in merged.columns:
            raise KeyError(f"Merged feature table missing `{feature}`.")
        _warn_missing_features(merged, (feature,))
        merged[feature] = pd.to_numeric(merged[feature], errors="coerce").fillna(0.0)

    return merged, input_nta_codes


def add_baseline_scores(df: pd.DataFrame) -> pd.DataFrame:
    z_cols: list[str] = []
    for feature in INDEX_FEATURES:
        z_col = Z_COLUMNS[feature]
        df[z_col] = _zscore(df[feature]).fillna(0.0)
        z_cols.append(z_col)
    df["baseline_stress_score"] = df[z_cols].mean(axis=1)
    df["baseline_rank"] = df["baseline_stress_score"].rank(
        method="min",
        ascending=False,
    ).astype(int)
    return df


def merge_event_delta(
    df: pd.DataFrame,
    data_dir: Path,
    input_nta_codes: set[str],
) -> tuple[pd.DataFrame, set[str]]:
    event_path = data_dir / "nta_event_delta.csv"
    event_df = pd.read_csv(event_path)
    if "NTACode" not in event_df.columns:
        raise KeyError(f"{event_path} missing `NTACode`.")
    if "delta" not in event_df.columns:
        raise KeyError(f"{event_path} missing `delta`.")

    input_nta_codes.update(event_df["NTACode"].astype(str))
    if "baseline_stress" in event_df.columns:
        event_df = event_df.drop(columns=["baseline_stress"])
    event_df = event_df.rename(columns={"delta": "event_delta"})

    merged = df.merge(
        event_df[["NTACode", "event_stress", "event_delta"]],
        on="NTACode",
        how="left",
    )
    for col in ("event_stress", "event_delta"):
        merged[col] = pd.to_numeric(merged[col], errors="coerce").fillna(0.0)

    merged["delta_rank"] = merged["event_delta"].rank(
        method="min",
        ascending=False,
    ).astype(int)
    return merged, input_nta_codes


def build_stress_index(data_dir: Path) -> pd.DataFrame:
    merged, input_nta_codes = merge_feature_tables(data_dir)
    merged = add_baseline_scores(merged)
    merged, input_nta_codes = merge_event_delta(merged, data_dir, input_nta_codes)

    missing_from_output = sorted(input_nta_codes - set(merged["NTACode"].astype(str)))
    if missing_from_output:
        print(
            "WARNING: NTAs present in input files but missing from final output:"
        )
        for nta_code in missing_from_output:
            print(f"  {nta_code}")

    return merged[list(OUTPUT_COLUMNS)]


def print_summary(df: pd.DataFrame) -> None:
    print(f"Total NTAs in final index: {len(df)}")

    print("Top 5 NTAs by baseline_stress_score:")
    top_baseline = df.nlargest(5, "baseline_stress_score")
    for _, row in top_baseline.iterrows():
        print(
            f"  {row['NTACode']} - {row['NTAName']}: "
            f"baseline_stress_score={row['baseline_stress_score']:.4g}, "
            f"baseline_rank={row['baseline_rank']}"
        )

    print("Top 5 NTAs by event_delta:")
    top_delta = df.nlargest(5, "event_delta")
    for _, row in top_delta.iterrows():
        print(
            f"  {row['NTACode']} - {row['NTAName']}: "
            f"event_delta={row['event_delta']:.4g}, "
            f"delta_rank={row['delta_rank']}"
        )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Merge baseline features and event deltas into the NTA stress index."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=get_project_root() / "data_processed" / "nta_stress_index.csv",
        help="Path for the merged stress index CSV.",
    )
    args = parser.parse_args(argv)

    data_dir = get_project_root() / "data_processed"
    args.output.parent.mkdir(parents=True, exist_ok=True)

    index_df = build_stress_index(data_dir)
    index_df.to_csv(args.output, index=False)
    print(f"Wrote: {args.output}")
    print_summary(index_df)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
