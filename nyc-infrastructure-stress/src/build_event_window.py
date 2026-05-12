"""
Build event-window datasets for NYC Infrastructure Stress analysis.

Adds a temporal event-window layer on top of the annual NTA stress index using
the two features with underlying timestamps in the source systems: MTA delays
and utility outage complaints.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

N_WEEKS = 52


def get_project_root() -> Path:
    """Project root is parent of `src/`."""
    return Path(__file__).resolve().parent.parent


def _zscore(values: np.ndarray | pd.Series) -> np.ndarray:
    """Z-score a vector with safe handling for zero variance."""
    x = np.asarray(values, dtype=float)
    mu = float(np.nanmean(x))
    sd = float(np.nanstd(x))
    if not np.isfinite(sd) or sd == 0.0:
        return np.zeros_like(x, dtype=float)
    return (x - mu) / sd


def _weekly_normal_params(annual_counts: np.ndarray, n_weeks: int = N_WEEKS) -> tuple[np.ndarray, np.ndarray]:
    """Derive weekly Normal(mean, std) parameters from annual NTA totals."""
    annual = np.asarray(annual_counts, dtype=float)
    weekly_mean = annual / float(n_weeks)
    weekly_std = np.sqrt(np.maximum(weekly_mean, 0.0))
    weekly_std = np.where(weekly_std > 0.0, weekly_std, 1e-9)
    return weekly_mean, weekly_std


def _simulate_weekly_nta_counts(
    rng: np.random.Generator,
    annual_counts: np.ndarray,
    n_weeks: int = N_WEEKS,
) -> np.ndarray:
    """
    Monte Carlo bootstrap: draw weekly NTA counts from Normal distributions.

    Source ETL outputs annual totals only, so weekly variation is simulated.
    """
    weekly_mean, weekly_std = _weekly_normal_params(annual_counts, n_weeks=n_weeks)
    draws = rng.normal(
        loc=weekly_mean[None, :],
        scale=weekly_std[None, :],
        size=(n_weeks, weekly_mean.shape[0]),
    )
    return np.clip(draws, 0.0, None)


def _load_annual_counts(df: pd.DataFrame, count_col: str, density_col: str, area_col: str = "area_km2") -> np.ndarray:
    if count_col in df.columns:
        return pd.to_numeric(df[count_col], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    density = pd.to_numeric(df[density_col], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    area = pd.to_numeric(df[area_col], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    return density * area


def detect_event_weeks(
    threshold: float = 1.5,
    seed: int = 7,
    output_path: Path | None = None,
) -> pd.DataFrame:
    """
    Flag citywide infrastructure event weeks from simulated weekly MTA and outage totals.

    The processed MTA and outage tables are annual NTA aggregates, so this function
    bootstraps 52 weekly citywide totals by drawing each NTA's weekly count from a
    Normal distribution whose mean and standard deviation come from that NTA's annual
    total. Weekly MTA and outage series are z-scored across the year, combined as
    their average, and weeks with combined z above the threshold are saved as events.
    """
    root = get_project_root()
    if output_path is None:
        output_path = root / "data_processed" / "event_weeks.csv"

    mta_df = pd.read_csv(root / "data_processed" / "nta_mta_delays.csv")
    out_df = pd.read_csv(root / "data_processed" / "nta_outages.csv")

    # Monte Carlo simulation: annual aggregates do not include weekly timestamps.
    rng = np.random.default_rng(int(seed))
    mta_weekly = _simulate_weekly_nta_counts(
        rng,
        _load_annual_counts(mta_df, "incident_count", "mob_mta_delay_density"),
    )
    out_weekly = _simulate_weekly_nta_counts(
        rng,
        _load_annual_counts(out_df, "complaint_count", "util_outage_density"),
    )

    citywide_mta_total = mta_weekly.sum(axis=1)
    citywide_outage_total = out_weekly.sum(axis=1)
    citywide_mta_z = _zscore(citywide_mta_total)
    citywide_outage_z = _zscore(citywide_outage_total)
    combined_z = (citywide_mta_z + citywide_outage_z) / 2.0
    is_event_week = combined_z > float(threshold)

    out = pd.DataFrame(
        {
            "week_index": np.arange(N_WEEKS, dtype=int),
            "citywide_mta_z": citywide_mta_z,
            "citywide_outage_z": citywide_outage_z,
            "combined_z": combined_z,
            "is_event_week": is_event_week,
        }
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(output_path, index=False)

    n_events = int(is_event_week.sum())
    print(f"Wrote: {output_path}")
    print(f"Detected {n_events} event weeks (combined_z > {threshold}).")
    return out


def _load_baseline_stress(root: Path) -> pd.DataFrame:
    candidates = [
        root / "data_processed" / "nta_stress_index.csv",
        root / "data_processed" / "baseline_index.csv",
    ]
    path = next((candidate for candidate in candidates if candidate.exists()), None)
    if path is None:
        raise FileNotFoundError(
            "Could not find baseline stress index. Expected one of:\n"
            + "\n".join(f"  - {candidate}" for candidate in candidates)
        )

    df = pd.read_csv(path)
    if "NTACode" not in df.columns and "nta2020" in df.columns:
        df = df.rename(columns={"nta2020": "NTACode"})
    if "NTAName" not in df.columns and "ntaname" in df.columns:
        df = df.rename(columns={"ntaname": "NTAName"})
    if "baseline_stress" not in df.columns:
        if "stress_score" in df.columns:
            df["baseline_stress"] = pd.to_numeric(df["stress_score"], errors="coerce").fillna(0.0)
        elif "baseline_stress_score" in df.columns:
            df["baseline_stress"] = pd.to_numeric(df["baseline_stress_score"], errors="coerce").fillna(0.0)
        else:
            raise KeyError(f"{path} missing baseline stress column.")

    return df[["NTACode", "NTAName", "baseline_stress"]].drop_duplicates("NTACode")


def compute_event_delta(
    seed: int = 7,
    output_path: Path | None = None,
    event_weeks_path: Path | None = None,
) -> pd.DataFrame:
    """
    Compare each NTA's baseline stress score to stress during flagged event weeks.

    Event weeks come from `event_weeks.csv`. For each flagged week, MTA and outage
    values are simulated per NTA from Normal distributions derived from annual totals,
    then averaged across event weeks. Those averages are z-scored across NTAs for MTA
    and outages and combined into an event stress score. Delta is event stress minus
    baseline stress: positive means more brittle during events, negative means more
    resilient than the annual baseline suggests.
    """
    root = get_project_root()
    if output_path is None:
        output_path = root / "data_processed" / "nta_event_delta.csv"
    if event_weeks_path is None:
        event_weeks_path = root / "data_processed" / "event_weeks.csv"

    baseline = _load_baseline_stress(root)

    if not event_weeks_path.exists():
        detect_event_weeks(seed=seed, output_path=event_weeks_path)

    event_weeks = pd.read_csv(event_weeks_path)
    if "is_event_week" not in event_weeks.columns:
        raise KeyError(f"{event_weeks_path} missing `is_event_week`.")
    if "week_index" not in event_weeks.columns:
        raise KeyError(f"{event_weeks_path} missing `week_index`.")

    event_indices = event_weeks.loc[event_weeks["is_event_week"] == True, "week_index"].to_numpy(dtype=int)  # noqa: E712
    if event_indices.size == 0:
        raise RuntimeError(f"No event weeks found in {event_weeks_path}.")

    mta_df = pd.read_csv(root / "data_processed" / "nta_mta_delays.csv")
    out_df = pd.read_csv(root / "data_processed" / "nta_outages.csv")
    if "NTACode" not in mta_df.columns or "NTACode" not in out_df.columns:
        raise KeyError("Processed MTA/outage tables must include `NTACode`.")

    ntas = (
        mta_df[["NTACode", "NTAName", "area_km2"]]
        .merge(out_df[["NTACode", "area_km2"]], on="NTACode", how="outer", suffixes=("", "_out"))
        .copy()
    )
    if "area_km2_out" in ntas.columns:
        ntas["area_km2"] = pd.to_numeric(ntas["area_km2"], errors="coerce").fillna(
            pd.to_numeric(ntas["area_km2_out"], errors="coerce")
        )
        ntas = ntas.drop(columns=["area_km2_out"])
    ntas["area_km2"] = pd.to_numeric(ntas["area_km2"], errors="coerce").fillna(0.0)

    mta_counts = _load_annual_counts(mta_df, "incident_count", "mob_mta_delay_density")
    out_counts = _load_annual_counts(out_df, "complaint_count", "util_outage_density")
    mta_counts = (
        pd.DataFrame({"NTACode": mta_df["NTACode"], "mta_count": mta_counts})
        .groupby("NTACode", as_index=False)["mta_count"]
        .sum()
        .merge(ntas[["NTACode"]], on="NTACode", how="right")["mta_count"]
        .fillna(0.0)
        .to_numpy(dtype=float)
    )
    out_counts = (
        pd.DataFrame({"NTACode": out_df["NTACode"], "out_count": out_counts})
        .groupby("NTACode", as_index=False)["out_count"]
        .sum()
        .merge(ntas[["NTACode"]], on="NTACode", how="right")["out_count"]
        .fillna(0.0)
        .to_numpy(dtype=float)
    )

    # Monte Carlo simulation: weekly per-NTA values are not available in source data.
    rng = np.random.default_rng(int(seed))
    mta_weekly = _simulate_weekly_nta_counts(rng, mta_counts)
    out_weekly = _simulate_weekly_nta_counts(rng, out_counts)

    area = ntas["area_km2"].replace(0, np.nan).to_numpy(dtype=float)
    mta_density = np.nan_to_num(mta_weekly[event_indices, :] / area[None, :], nan=0.0)
    out_density = np.nan_to_num(out_weekly[event_indices, :] / area[None, :], nan=0.0)
    avg_mta_density = mta_density.mean(axis=0)
    avg_out_density = out_density.mean(axis=0)
    event_stress = (_zscore(avg_mta_density) + _zscore(avg_out_density)) / 2.0

    out = ntas[["NTACode", "NTAName"]].copy()
    out["event_stress"] = event_stress
    out = out.merge(baseline, on=["NTACode", "NTAName"], how="left")
    out["baseline_stress"] = pd.to_numeric(out["baseline_stress"], errors="coerce").fillna(0.0)
    out["delta"] = out["event_stress"] - out["baseline_stress"]
    out = out[["NTACode", "NTAName", "baseline_stress", "event_stress", "delta"]].sort_values(
        "delta", ascending=False
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(output_path, index=False)

    print(f"Wrote: {output_path}")
    print("Top 5 NTAs by positive delta (most brittle during events):")
    for _, row in out.head(5).iterrows():
        print(
            f"  {row['NTACode']} - {row['NTAName']}: "
            f"baseline={row['baseline_stress']:.4g}, "
            f"event={row['event_stress']:.4g}, "
            f"delta={row['delta']:.4g}"
        )

    print("Top 5 NTAs by negative delta (most resilient during events):")
    for _, row in out.nsmallest(5, "delta").iterrows():
        print(
            f"  {row['NTACode']} - {row['NTAName']}: "
            f"baseline={row['baseline_stress']:.4g}, "
            f"event={row['event_stress']:.4g}, "
            f"delta={row['delta']:.4g}"
        )

    return out


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build event-window datasets for stress analysis.")
    sub = parser.add_subparsers(dest="command", required=True)

    detect = sub.add_parser("detect-event-weeks", help="Detect anomalous citywide event weeks.")
    detect.add_argument("--threshold", type=float, default=1.5)
    detect.add_argument("--seed", type=int, default=7)
    detect.add_argument(
        "--output",
        type=Path,
        default=get_project_root() / "data_processed" / "event_weeks.csv",
    )

    delta = sub.add_parser("compute-event-delta", help="Compute per-NTA stress deltas for event weeks.")
    delta.add_argument("--seed", type=int, default=7)
    delta.add_argument(
        "--event-weeks",
        type=Path,
        default=get_project_root() / "data_processed" / "event_weeks.csv",
    )
    delta.add_argument(
        "--output",
        type=Path,
        default=get_project_root() / "data_processed" / "nta_event_delta.csv",
    )

    args = parser.parse_args(argv)

    if args.command == "detect-event-weeks":
        detect_event_weeks(threshold=args.threshold, seed=args.seed, output_path=args.output)
        return

    if args.command == "compute-event-delta":
        compute_event_delta(seed=args.seed, event_weeks_path=args.event_weeks, output_path=args.output)
        return

    raise RuntimeError(f"Unknown command: {args.command}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
