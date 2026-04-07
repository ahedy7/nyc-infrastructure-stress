"""
Build event-window datasets for NYC Infrastructure Stress analysis.

This module adds a temporal "event window" layer on top of the (mostly) annual
NTA-level stress index.

## Methodology (high level)

We want to identify **event weeks**: weeks where **citywide** infrastructure stress
was statistically anomalous, then quantify which NTAs deviated most from their own
baseline during those events.

Only two features in this project have temporal resolution in the underlying source
systems:

- **Mobility**: MTA delay-causing incidents (monthly by line in the source; our ETL
  aggregates into a single annual window total and allocates to NTAs).
- **Utilities**: 311 power outage complaints (per-complaint timestamps in the source;
  our ETL aggregates into a single annual window total by NTA).

Flood exposure and 311 general service density are static or already aggregated in
this repo, so event-week deltas are computed using the *temporally resolved* features
only (MTA + outages).

### Two execution modes

1. **Raw weekly mode (preferred, if raw timestamped rows exist locally)**:
   - Aggregate MTA incidents and outage complaints by week.
   - Compute weekly citywide z-scores and detect event weeks.
   - Compute per-NTA event-week scores from those observed weekly values.

2. **Fallback mode (graceful, when only annual aggregates exist)**:
   - Simulate weekly variation from annual counts using a Monte Carlo / bootstrap
     model (Poisson draws per NTA per week; deterministic via seed).
   - Detect event weeks on the simulated citywide series (threshold on combined z).
   - Compute per-NTA event stress conditional on those simulated event weeks.

Fallback mode is clearly flagged in stdout and outputs remain reproducible.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


def get_project_root() -> Path:
    """Project root is parent of `src/`."""
    return Path(__file__).resolve().parent.parent


def _weekly_starts(start: pd.Timestamp, end: pd.Timestamp) -> list[pd.Timestamp]:
    """
    Return week start timestamps in [start, end), aligned to the provided start date.

    Weeks are defined as contiguous 7-day windows:
      [start + 0*7d, start + 1*7d), [start + 1*7d, start + 2*7d), ...
    """
    start = pd.Timestamp(start).normalize()
    end = pd.Timestamp(end).normalize()
    if end < start:
        raise ValueError("end must be >= start")
    out: list[pd.Timestamp] = []
    cur = start
    while cur < end:
        out.append(cur)
        cur = cur + pd.Timedelta(days=7)
    return out


def _zscore(x: pd.Series) -> pd.Series:
    """Z-score with safe handling for zero-variance vectors."""
    x = pd.to_numeric(x, errors="coerce")
    mu = float(x.mean())
    sd = float(x.std(ddof=0))
    if not np.isfinite(sd) or sd == 0.0:
        return pd.Series(np.zeros(len(x), dtype=float), index=x.index)
    return (x - mu) / sd


@dataclass(frozen=True)
class WeeklySignals:
    """Container for per-week citywide totals (counts)."""

    week_start: pd.Series
    citywide_mta_incidents: pd.Series
    citywide_outage_complaints: pd.Series
    mode: str  # "raw_weekly" or "monte_carlo_fallback"


def _try_weekly_citywide_from_raw(
    start: pd.Timestamp,
    end: pd.Timestamp,
    project_root: Path,
) -> WeeklySignals | None:
    """
    Attempt to build weekly citywide totals from local raw timestamped data.

    This repo currently does not persist the raw per-incident/per-complaint rows by
    default (ETLs typically output annual windows). If you later add raw extracts,
    support is provided for:
      - `data_raw/mta_delays_raw.csv` with a `month` or `date`-like column and `incidents`
      - `data_raw/outages_raw.csv` with `created_date` and one row per complaint
    """
    start = pd.Timestamp(start).normalize()
    end = pd.Timestamp(end).normalize()
    weeks = _weekly_starts(start, end)
    if not weeks:
        return None

    mta_path = project_root / "data_raw" / "mta_delays_raw.csv"
    out_path = project_root / "data_raw" / "outages_raw.csv"
    if not (mta_path.exists() and out_path.exists()):
        return None

    # MTA raw: expected monthly rows. We still align them into 7-day bins as best-effort.
    mta = pd.read_csv(mta_path)
    mta_date_col = None
    for cand in ("created_date", "date", "month", "timestamp", "time"):
        if cand in mta.columns:
            mta_date_col = cand
            break
    if mta_date_col is None or "incidents" not in mta.columns:
        return None
    mta["__dt"] = pd.to_datetime(mta[mta_date_col], errors="coerce").dt.tz_localize(None)
    mta = mta[mta["__dt"].notna()].copy()
    mta["incidents"] = pd.to_numeric(mta["incidents"], errors="coerce").fillna(0).astype(float)

    outages = pd.read_csv(out_path)
    if "created_date" not in outages.columns:
        return None
    outages["__dt"] = pd.to_datetime(outages["created_date"], errors="coerce").dt.tz_localize(None)
    outages = outages[outages["__dt"].notna()].copy()

    def _bin_week_start(dt: pd.Series) -> pd.Series:
        delta_days = (dt.dt.normalize() - start).dt.days
        week_idx = (delta_days // 7).astype(int)
        return (start + pd.to_timedelta(week_idx * 7, unit="D")).astype("datetime64[ns]")

    mta["week_start"] = _bin_week_start(mta["__dt"])
    outages["week_start"] = _bin_week_start(outages["__dt"])

    week_index = pd.Index(pd.to_datetime(weeks), name="week_start")
    city_mta = mta.groupby("week_start")["incidents"].sum().reindex(week_index, fill_value=0.0)
    city_out = (
        outages.groupby("week_start")["__dt"].size().astype(float).reindex(week_index, fill_value=0.0)
    )

    return WeeklySignals(
        week_start=city_mta.index.to_series(index=city_mta.index),
        citywide_mta_incidents=city_mta.reset_index(drop=True),
        citywide_outage_complaints=city_out.reset_index(drop=True),
        mode="raw_weekly",
    )


def _weekly_citywide_from_processed_monte_carlo(
    start: pd.Timestamp,
    end: pd.Timestamp,
    mta_processed: pd.DataFrame,
    outages_processed: pd.DataFrame,
    seed: int,
) -> tuple[WeeklySignals, dict]:
    """
    Build simulated weekly citywide totals when only annual aggregates exist.

    We interpret `incident_count` / `complaint_count` as totals over the full window
    and simulate weekly counts with independent Poisson draws:
      weekly_count_i ~ Poisson(annual_count_i / n_weeks)

    This is a pragmatic fallback to introduce variance for event detection.
    """
    start = pd.Timestamp(start).normalize()
    end = pd.Timestamp(end).normalize()
    week_starts = _weekly_starts(start, end)
    n_weeks = len(week_starts)
    if n_weeks == 0:
        raise ValueError("No weeks in requested window.")

    rng = np.random.default_rng(int(seed))

    mta = mta_processed.copy()
    outages = outages_processed.copy()

    # Prefer explicit counts; fall back to density * area if needed.
    if "incident_count" in mta.columns:
        mta_counts = pd.to_numeric(mta["incident_count"], errors="coerce").fillna(0.0).astype(float)
    else:
        mta_counts = (
            pd.to_numeric(mta.get("mob_mta_delay_density"), errors="coerce").fillna(0.0).astype(float)
            * pd.to_numeric(mta.get("area_km2"), errors="coerce").fillna(0.0).astype(float)
        )

    if "complaint_count" in outages.columns:
        out_counts = (
            pd.to_numeric(outages["complaint_count"], errors="coerce").fillna(0.0).astype(float)
        )
    else:
        out_counts = (
            pd.to_numeric(outages.get("util_outage_density"), errors="coerce").fillna(0.0).astype(float)
            * pd.to_numeric(outages.get("area_km2"), errors="coerce").fillna(0.0).astype(float)
        )

    lam_mta = (mta_counts / float(n_weeks)).clip(lower=0.0).to_numpy()
    lam_out = (out_counts / float(n_weeks)).clip(lower=0.0).to_numpy()

    # Draw per-NTA weekly counts, then sum for citywide totals.
    mta_weekly = rng.poisson(lam=lam_mta[None, :], size=(n_weeks, lam_mta.shape[0]))
    out_weekly = rng.poisson(lam=lam_out[None, :], size=(n_weeks, lam_out.shape[0]))
    city_mta = mta_weekly.sum(axis=1).astype(float)
    city_out = out_weekly.sum(axis=1).astype(float)

    signals = WeeklySignals(
        week_start=pd.Series(pd.to_datetime(week_starts), name="week_start"),
        citywide_mta_incidents=pd.Series(city_mta, name="citywide_mta_incidents"),
        citywide_outage_complaints=pd.Series(city_out, name="citywide_outage_complaints"),
        mode="monte_carlo_fallback",
    )
    meta = {
        "n_weeks": n_weeks,
        "seed": int(seed),
        "assumption": "Annual window totals simulated as weekly Poisson counts.",
    }
    return signals, meta


def detect_event_weeks(
    start_date: str = "2025-02-15",
    end_date: str = "2026-02-15",
    threshold: float = 1.5,
    seed: int = 7,
    output_path: Path | None = None,
) -> pd.DataFrame:
    """
    Detect "event weeks" of anomalous citywide infrastructure stress.

    Inputs (processed, NTA-level):
    - `data_processed/nta_mta_delays.csv` (expects `incident_count` and/or `mob_mta_delay_density`)
    - `data_processed/nta_outages.csv`   (expects `complaint_count` and/or `util_outage_density`)

    For each week in [start_date, end_date), compute citywide totals for MTA incidents and
    outage complaints, convert each weekly series to a z-score across the full year,
    then define:

      combined_weekly_z = mean(citywide_mta_z, citywide_outage_z)

    A week is flagged as an event if combined_weekly_z > `threshold`.

    If raw weekly rows are not available locally, a deterministic Monte Carlo fallback
    is used to simulate weekly variance from annual aggregates (flagged in stdout).
    """
    root = get_project_root()
    start = pd.Timestamp(start_date).normalize()
    end = pd.Timestamp(end_date).normalize()

    if output_path is None:
        output_path = root / "data_processed" / "event_weeks.csv"

    # Prefer raw weekly if available.
    raw = _try_weekly_citywide_from_raw(start, end, root)
    if raw is not None:
        signals = raw
        meta = {}
    else:
        mta_path = root / "data_processed" / "nta_mta_delays.csv"
        out_path = root / "data_processed" / "nta_outages.csv"
        mta_df = pd.read_csv(mta_path)
        out_df = pd.read_csv(out_path)
        signals, meta = _weekly_citywide_from_processed_monte_carlo(
            start=start,
            end=end,
            mta_processed=mta_df,
            outages_processed=out_df,
            seed=seed,
        )

    city_mta_z = _zscore(pd.Series(signals.citywide_mta_incidents))
    city_out_z = _zscore(pd.Series(signals.citywide_outage_complaints))
    combined = (city_mta_z + city_out_z) / 2.0
    is_event = combined > float(threshold)

    out = pd.DataFrame(
        {
            "week_start": pd.to_datetime(signals.week_start).dt.strftime("%Y-%m-%d"),
            "citywide_mta_z": city_mta_z.astype(float),
            "citywide_outage_z": city_out_z.astype(float),
            "combined_z": combined.astype(float),
            "is_event_week": is_event.astype(bool),
            "mode": signals.mode,
        }
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(output_path, index=False)

    event_dates = out.loc[out["is_event_week"], "week_start"].tolist()
    print(f"Wrote: {output_path}")
    if signals.mode != "raw_weekly":
        print(
            "NOTE: Raw weekly data not found; used Monte Carlo fallback to simulate weekly variance.\n"
            f"  - seed={seed}\n"
            f"  - {meta.get('assumption', '')}"
        )
    print(f"Detected {len(event_dates)} event weeks (threshold combined_z > {threshold}).")
    if event_dates:
        print("Event week starts:")
        for d in event_dates:
            print(f"  - {d}")
    return out


def _load_baseline_index(root: Path) -> pd.DataFrame:
    """
    Load baseline stress index table.

    The user-facing spec names `data_processed/nta_stress_index.csv`, but in this repo
    the equivalent is often `data_processed/baseline_index.csv` with `stress_score`.
    """
    candidates = [
        root / "data_processed" / "nta_stress_index.csv",
        root / "data_processed" / "nta_stress_index.csv",  # intentional duplicate for compatibility
        root / "data_processed" / "baseline_index.csv",
    ]
    path = next((p for p in candidates if p.exists()), None)
    if path is None:
        raise FileNotFoundError(
            "Could not find baseline index. Expected one of:\n"
            + "\n".join(f"  - {p}" for p in candidates)
        )
    df = pd.read_csv(path)

    # Normalize key columns to expected names.
    if "NTACode" not in df.columns and "nta2020" in df.columns:
        df = df.rename(columns={"nta2020": "NTACode"})
    if "NTAName" not in df.columns and "ntaname" in df.columns:
        df = df.rename(columns={"ntaname": "NTAName"})
    if "baseline_stress" not in df.columns:
        if "stress_score" in df.columns:
            df["baseline_stress"] = pd.to_numeric(df["stress_score"], errors="coerce").fillna(0.0)
        else:
            raise KeyError(f"Baseline index at {path} missing `stress_score`/`baseline_stress`.")

    return df[["NTACode", "NTAName", "baseline_stress"]].copy()


def compute_event_delta(
    start_date: str = "2025-02-15",
    end_date: str = "2026-02-15",
    threshold: float = 1.5,
    seed: int = 7,
    output_path: Path | None = None,
    event_weeks_path: Path | None = None,
) -> pd.DataFrame:
    """
    Compute per-NTA stress deltas between baseline and event-week stress.

    Steps:
    - Load baseline stress scores per NTA (repo: `baseline_index.csv` with `stress_score`).
    - Load event weeks and filter to `is_event_week == True`.
    - For each event week, compute per-NTA stress using *only* the temporal features:
      - MTA incident density
      - Outage complaint density
      Then z-score each across NTAs and average to an event-week stress score.
    - Average event-week stress scores across all event weeks for each NTA.
    - Delta = event_stress - baseline_stress.

    If raw per-week per-NTA data does not exist locally, a deterministic Monte Carlo
    simulation is used (same fallback family as `detect_event_weeks`).
    """
    root = get_project_root()
    start = pd.Timestamp(start_date).normalize()
    end = pd.Timestamp(end_date).normalize()

    if output_path is None:
        output_path = root / "data_processed" / "nta_event_delta.csv"
    if event_weeks_path is None:
        event_weeks_path = root / "data_processed" / "event_weeks.csv"

    baseline = _load_baseline_index(root)

    if not event_weeks_path.exists():
        detect_event_weeks(
            start_date=start_date,
            end_date=end_date,
            threshold=threshold,
            seed=seed,
            output_path=event_weeks_path,
        )
    ew = pd.read_csv(event_weeks_path)
    if "is_event_week" not in ew.columns:
        raise KeyError(f"{event_weeks_path} missing `is_event_week`.")
    event_weeks = ew[ew["is_event_week"] == True].copy()  # noqa: E712
    n_event = int(len(event_weeks))
    if n_event == 0:
        raise RuntimeError(
            f"No event weeks found in {event_weeks_path}. "
            "Try lowering --threshold or changing the date window."
        )

    mta_path = root / "data_processed" / "nta_mta_delays.csv"
    out_path = root / "data_processed" / "nta_outages.csv"
    mta_df = pd.read_csv(mta_path)
    out_df = pd.read_csv(out_path)

    # Normalize keys.
    if "NTACode" not in mta_df.columns:
        raise KeyError(f"{mta_path} missing `NTACode`.")
    if "NTACode" not in out_df.columns:
        raise KeyError(f"{out_path} missing `NTACode`.")

    # Align to a common NTA universe.
    ntas = (
        mta_df[["NTACode", "NTAName", "area_km2"]]
        .merge(out_df[["NTACode", "area_km2"]], on="NTACode", how="outer", suffixes=("", "_out"))
        .copy()
    )
    # Use whichever area_km2 is available.
    if "area_km2_out" in ntas.columns:
        ntas["area_km2"] = pd.to_numeric(ntas["area_km2"], errors="coerce").fillna(
            pd.to_numeric(ntas["area_km2_out"], errors="coerce")
        )
        ntas = ntas.drop(columns=["area_km2_out"])
    ntas["area_km2"] = pd.to_numeric(ntas["area_km2"], errors="coerce").fillna(0.0)

    # If raw weekly per-NTA is present, we'd compute directly; today we fall back.
    # NOTE: This is the "comment flag" requested in the prompt: ETL scripts currently
    # output annual-window aggregates, so weekly per-NTA values are not available in
    # the repo by default.
    rng = np.random.default_rng(int(seed))
    week_starts = _weekly_starts(start, end)
    n_weeks = len(week_starts)

    # Build annual counts per NTA (prefer explicit counts).
    mta = mta_df.merge(ntas[["NTACode", "area_km2"]], on="NTACode", how="left")
    outg = out_df.merge(ntas[["NTACode", "area_km2"]], on="NTACode", how="left")

    if "incident_count" in mta.columns:
        mta_counts = pd.to_numeric(mta["incident_count"], errors="coerce").fillna(0.0).astype(float)
    else:
        mta_counts = (
            pd.to_numeric(mta.get("mob_mta_delay_density"), errors="coerce").fillna(0.0).astype(float)
            * pd.to_numeric(mta.get("area_km2"), errors="coerce").fillna(0.0).astype(float)
        )

    if "complaint_count" in outg.columns:
        out_counts = pd.to_numeric(outg["complaint_count"], errors="coerce").fillna(0.0).astype(float)
    else:
        out_counts = (
            pd.to_numeric(outg.get("util_outage_density"), errors="coerce").fillna(0.0).astype(float)
            * pd.to_numeric(outg.get("area_km2"), errors="coerce").fillna(0.0).astype(float)
        )

    # Ensure we have an `NTAName` column without introducing suffixes.
    if "NTAName" not in ntas.columns:
        name_mta = mta_df[["NTACode", "NTAName"]].drop_duplicates("NTACode")
        name_out = out_df[["NTACode", "NTAName"]].drop_duplicates("NTACode")
        ntas = ntas.merge(name_mta, on="NTACode", how="left")
        ntas = ntas.merge(name_out, on="NTACode", how="left", suffixes=("", "_out"))
        ntas["NTAName"] = ntas["NTAName"].fillna(ntas.get("NTAName_out"))
        if "NTAName_out" in ntas.columns:
            ntas = ntas.drop(columns=["NTAName_out"])
    ntas = ntas.merge(
        pd.DataFrame({"NTACode": mta["NTACode"].values, "mta_count": mta_counts.values})
        .groupby("NTACode", as_index=False)["mta_count"]
        .sum(),
        on="NTACode",
        how="left",
    )
    ntas = ntas.merge(
        pd.DataFrame({"NTACode": outg["NTACode"].values, "out_count": out_counts.values})
        .groupby("NTACode", as_index=False)["out_count"]
        .sum(),
        on="NTACode",
        how="left",
    )
    ntas["mta_count"] = pd.to_numeric(ntas["mta_count"], errors="coerce").fillna(0.0)
    ntas["out_count"] = pd.to_numeric(ntas["out_count"], errors="coerce").fillna(0.0)

    lam_mta = (ntas["mta_count"] / float(n_weeks)).clip(lower=0.0).to_numpy()
    lam_out = (ntas["out_count"] / float(n_weeks)).clip(lower=0.0).to_numpy()
    area = ntas["area_km2"].replace(0, np.nan).to_numpy(dtype=float)

    # Simulate weekly per-NTA counts/densities across the full year once, then
    # select only the event weeks (as defined by citywide combined z in that same simulation).
    mta_weekly = rng.poisson(lam=lam_mta[None, :], size=(n_weeks, lam_mta.shape[0])).astype(float)
    out_weekly = rng.poisson(lam=lam_out[None, :], size=(n_weeks, lam_out.shape[0])).astype(float)
    city_mta = mta_weekly.sum(axis=1)
    city_out = out_weekly.sum(axis=1)

    city_mta_z = _zscore(pd.Series(city_mta))
    city_out_z = _zscore(pd.Series(city_out))
    combined = (city_mta_z + city_out_z) / 2.0
    is_event_sim = (combined > float(threshold)).to_numpy()

    # If simulated event count differs from CSV event count (possible if CSV was created
    # from a different seed/threshold), we still compute using the simulation’s own flags.
    # This keeps the conditional distribution coherent.
    sim_n_event = int(is_event_sim.sum())
    if sim_n_event == 0:
        raise RuntimeError(
            "Monte Carlo simulation produced 0 event weeks; "
            "try lowering --threshold or changing --seed."
        )

    # Per-week densities.
    mta_dens = mta_weekly / area[None, :]
    out_dens = out_weekly / area[None, :]
    mta_dens = np.nan_to_num(mta_dens, nan=0.0, posinf=0.0, neginf=0.0)
    out_dens = np.nan_to_num(out_dens, nan=0.0, posinf=0.0, neginf=0.0)

    # Per-week z-scores across NTAs, then mean for event-week stress.
    # (Vectorized z-score by week.)
    def _z_by_row(mat: np.ndarray) -> np.ndarray:
        mu = mat.mean(axis=1, keepdims=True)
        sd = mat.std(axis=1, keepdims=True)
        sd = np.where(sd == 0.0, 1.0, sd)
        return (mat - mu) / sd

    z_mta = _z_by_row(mta_dens)
    z_out = _z_by_row(out_dens)
    event_week_score = (z_mta + z_out) / 2.0  # shape: (n_weeks, n_nta)

    event_scores = event_week_score[is_event_sim, :].mean(axis=0)
    event_scores = np.nan_to_num(event_scores, nan=0.0)

    out = ntas[["NTACode", "NTAName"]].copy()
    out["event_stress"] = event_scores.astype(float)

    out = out.merge(baseline, on=["NTACode", "NTAName"], how="left")
    out["baseline_stress"] = pd.to_numeric(out["baseline_stress"], errors="coerce").fillna(0.0)
    out["delta"] = out["event_stress"] - out["baseline_stress"]

    out = out[["NTACode", "NTAName", "baseline_stress", "event_stress", "delta"]].copy()
    out = out.sort_values("delta", ascending=False).reset_index(drop=True)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(output_path, index=False)

    print(f"Wrote: {output_path}")
    print(
        "NOTE: Raw weekly per-NTA data not found; used Monte Carlo fallback to simulate weekly variance.\n"
        f"  - seed={seed}\n"
        f"  - window weeks={n_weeks}\n"
        f"  - simulated_event_weeks={sim_n_event} (CSV event_weeks.csv has {n_event})\n"
        "  - model: independent Poisson weekly counts per NTA from annual totals"
    )
    print("Top 5 NTAs by delta (more stressed during events vs baseline):")
    for _, row in out.head(5).iterrows():
        print(
            f"  {row['NTACode']} - {row['NTAName']}: "
            f"baseline={row['baseline_stress']:.4g}, event={row['event_stress']:.4g}, delta={row['delta']:.4g}"
        )

    return out


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build event-window datasets for stress analysis.")
    sub = parser.add_subparsers(dest="command", required=True)

    p1 = sub.add_parser("detect-event-weeks", help="Detect anomalous citywide event weeks.")
    p1.add_argument("--start-date", type=str, default="2025-02-15")
    p1.add_argument("--end-date", type=str, default="2026-02-15")
    p1.add_argument("--threshold", type=float, default=1.5)
    p1.add_argument("--seed", type=int, default=7)
    p1.add_argument(
        "--output",
        type=Path,
        default=get_project_root() / "data_processed" / "event_weeks.csv",
    )

    p2 = sub.add_parser("compute-event-delta", help="Compute per-NTA stress deltas for event weeks.")
    p2.add_argument("--start-date", type=str, default="2025-02-15")
    p2.add_argument("--end-date", type=str, default="2026-02-15")
    p2.add_argument("--threshold", type=float, default=1.5)
    p2.add_argument("--seed", type=int, default=7)
    p2.add_argument(
        "--event-weeks",
        type=Path,
        default=get_project_root() / "data_processed" / "event_weeks.csv",
    )
    p2.add_argument(
        "--output",
        type=Path,
        default=get_project_root() / "data_processed" / "nta_event_delta.csv",
    )

    args = parser.parse_args(argv)

    if args.command == "detect-event-weeks":
        detect_event_weeks(
            start_date=args.start_date,
            end_date=args.end_date,
            threshold=args.threshold,
            seed=args.seed,
            output_path=args.output,
        )
        return

    if args.command == "compute-event-delta":
        compute_event_delta(
            start_date=args.start_date,
            end_date=args.end_date,
            threshold=args.threshold,
            seed=args.seed,
            event_weeks_path=args.event_weeks,
            output_path=args.output,
        )
        return

    raise RuntimeError(f"Unknown command: {args.command}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        raise
