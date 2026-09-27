"""Turn one flight folder's raw data into cleaned, standard-schema tables."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .readers import reader_for, wind_ros2

EARTH_RADIUS_M = 6_371_000.0
WIND_MARGIN_S = 5.0


@dataclass
class Session:
    source: Path
    flight: pd.DataFrame
    info: dict
    wind: pd.DataFrame | None = None
    wind_info: dict = field(default_factory=dict)

    @property
    def stem(self) -> str:
        return self.source.stem


def add_local_position(df: pd.DataFrame) -> dict:
    """Add north_m / east_m relative to home (position at arming, else first valid fix)."""
    valid = df["lat_deg"].notna() & (df["lat_deg"].abs() > 0.1)
    armed_valid = valid & df["armed"]
    idx = armed_valid.idxmax() if armed_valid.any() else (valid.idxmax() if valid.any() else None)
    if idx is None:
        df["north_m"] = np.nan
        df["east_m"] = np.nan
        return {}
    lat0, lon0 = float(df.at[idx, "lat_deg"]), float(df.at[idx, "lon_deg"])
    lat = df["lat_deg"].where(valid)
    lon = df["lon_deg"].where(valid)
    df["north_m"] = (np.radians(lat - lat0) * EARTH_RADIUS_M).round(3)
    df["east_m"] = (np.radians(lon - lon0) * EARTH_RADIUS_M * np.cos(np.radians(lat0))).round(3)
    return {"lat_deg": round(lat0, 7), "lon_deg": round(lon0, 7)}


def trim_wind(wind: pd.DataFrame, flight: pd.DataFrame, margin_s: float = WIND_MARGIN_S):
    """Cut the wind log to the flight's time window, both on the GPS-corrected UTC clock.

    The wind-drone timestamps are taken as true UTC. The flight's host clock is shifted onto the
    autopilot's GPS time first (``time_gps_utc``), so a drifting logger clock does not shift the
    window.
    """
    t0 = flight["time_gps_utc"].min()
    t1 = flight["time_gps_utc"].max()
    lo, hi = t0 - pd.Timedelta(seconds=margin_s), t1 + pd.Timedelta(seconds=margin_s)
    cut = wind[(wind["time_utc"] >= lo) & (wind["time_utc"] <= hi)].copy()
    cut["elapsed_s"] = (
        (cut["time_utc"] - t0).dt.total_seconds() + float(flight["elapsed_s"].iloc[0])
    ).round(3)
    cut = cut[["time_utc", "sensor_stamp_utc", "elapsed_s", "wind_speed_m_s", "wind_dir_deg",
               "wind_z", "temperature_c"]].reset_index(drop=True)

    flight_s = (t1 - t0).total_seconds()
    if len(cut):
        ov0 = max(t0, cut["time_utc"].min())
        ov1 = min(t1, cut["time_utc"].max())
        covered = max(0.0, (ov1 - ov0).total_seconds())
    else:
        covered = 0.0
    info = {
        "wind_log_start_utc": wind["time_utc"].min().isoformat(),
        "wind_log_end_utc": wind["time_utc"].max().isoformat(),
        "flight_start_gps_utc": t0.isoformat(),
        "flight_end_gps_utc": t1.isoformat(),
        "margin_s": margin_s,
        "rows": int(len(cut)),
        "coverage_pct": round(100 * covered / flight_s, 1) if flight_s > 0 else 0.0,
    }
    return cut, info


def load_session(csv_path: Path) -> Session | None:
    reader = reader_for(csv_path)
    if reader is None:
        return None
    df, info = reader.read(csv_path)
    info["home"] = add_local_position(df)
    sess = Session(source=csv_path, flight=df, info=info)

    wind_dirs = wind_ros2.find(csv_path.parent)
    if wind_dirs:
        parts, sources = [], []
        for d in wind_dirs:
            parts.append(wind_ros2.read(d))
            sources.append(d.name)
        wind = pd.concat(parts).sort_values("time_utc").reset_index(drop=True)
        sess.wind, sess.wind_info = trim_wind(wind, df)
        sess.wind_info["sources"] = sources
        sess.wind_info["reader"] = wind_ros2.NAME
    return sess


def find_flight_dirs(root: Path) -> list[Path]:
    return sorted(p.parent for p in root.glob("*/raw_data") if p.is_dir())


def raw_logs(flight_dir: Path) -> list[Path]:
    return sorted((flight_dir / "raw_data").glob("*.csv"))
