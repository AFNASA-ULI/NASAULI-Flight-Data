"""Reader for the early (April 2026) logger CSV, called "v1" here.

Layout: no preamble; a header row starting ``Min-Sec, RTC_UTC, GPS_UTC, GPS_Synced, ...``, values padded
with spaces. About 13 Hz. There is no heartbeat, flight mode, VFR, servo, vibration or EKF data.

Several unit labels in the header are wrong; the values are the raw MAVLink fields:

* ``IMU_*_acc_cm/s^2`` are SCALED_IMU milli-g (z ≈ -1000 at rest)
* ``IMU_*_gyro_Rad/s`` are milliradians/s (they equal ``IMU_*_Speed_Rads/s`` x 1000)
* ``IMU_*_mag_Rad/s`` are milligauss
* ``RawGPS_vel_m/s`` is GPS_RAW_INT ``vel`` in cm/s
* ``FusedGPS_vel*_cm/s`` are cm/s and ``FusedGPS_head`` is degrees

Time: ``Min-Sec`` is the logger clock (minutes-seconds within the hour). ``GPS_UTC`` is valid once
``GPS_Synced`` is True; the offset between the two is used to put every row on UTC.
``Battery_*`` came from a sensor that was not connected (constant ~35 A / 10.9 V); ``PM_*`` is the
autopilot's power module.

The ``*_Fixed.csv`` files next to these logs are hand-cleaned copies and are not read.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

from ..schema import FLIGHT_COLUMNS

NAME = "legacy_v1"
FIRST_COLUMNS = ["Min-Sec", "RTC_UTC", "GPS_UTC", "GPS_Synced"]

G = 9.80665
DEG = 180.0 / math.pi

COLUMN_MAP = {
    "roll_deg": ("IMU_Roll_Rads", DEG),
    "pitch_deg": ("IMU_Pitch_Rads", DEG),
    "yaw_deg": ("IMU_Yaw_Rads", DEG),
    "roll_rate_deg_s": ("IMU_Roll_Speed_Rads/s", DEG),
    "pitch_rate_deg_s": ("IMU_Pitch_Speed_Rads/s", DEG),
    "yaw_rate_deg_s": ("IMU_Yaw_Speed_Rads/s", DEG),
    "acc_x_m_s2": ("IMU_X_acc_cm/s^2", G / 1000),
    "acc_y_m_s2": ("IMU_Y_acc_cm/s^2", G / 1000),
    "acc_z_m_s2": ("IMU_Z_acc_cm/s^2", G / 1000),
    "gyro_x_rad_s": ("IMU_X_gyro_Rad/s", 1 / 1000),
    "gyro_y_rad_s": ("IMU_Y_gyro_Rad/s", 1 / 1000),
    "gyro_z_rad_s": ("IMU_Z_gyro_Rad/s", 1 / 1000),
    "mag_x_mgauss": ("IMU_X_mag_Rad/s", 1),
    "mag_y_mgauss": ("IMU_Y_mag_Rad/s", 1),
    "mag_z_mgauss": ("IMU_Z_mag_Rad/s", 1),
    "gps_lat_deg": ("RawGPS_Lat", 1),
    "gps_lon_deg": ("RawGPS_Lon", 1),
    "gps_alt_m": ("RawGPS_alt_mm", 1 / 1000),
    "gps_speed_m_s": ("RawGPS_vel_m/s", 1 / 100),
    "gps_sats": ("RawGPS_sats", 1),
    "lat_deg": ("FusedGPS_Lat", 1),
    "lon_deg": ("FusedGPS_Lon", 1),
    "alt_msl_m": ("FusedGPS_alt_msl_mm", 1 / 1000),
    "alt_rel_m": ("FusedGPS_alt_rel_mm", 1 / 1000),
    "vel_n_m_s": ("FusedGPS_velx_cm/s", 1 / 100),
    "vel_e_m_s": ("FusedGPS_vely_cm/s", 1 / 100),
    "vel_d_m_s": ("FusedGPS_velz_cm/s", 1 / 100),
    "heading_deg": ("FusedGPS_head", 1),
    "batt_voltage_v": ("PM_Voltage_V", 1),
    "batt_current_a": ("PM_Current_A", 1),
    "batt_consumed_mah": ("PM_Consumed_mAh", 1),
    "batt_remaining_pct": ("PM_Remaining_Pct", 1),
    "batt_temp_c": ("Battery_Temp_C", 1),
}


def sniff(path: Path) -> bool:
    if path.stem.endswith("_Fixed"):
        return False
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            cols = [c.strip() for c in f.readline().split(",")]
    except OSError:
        return False
    return cols[:4] == FIRST_COLUMNS


def _logger_seconds(minsec: pd.Series) -> pd.Series:
    """'MM-SS.sss' within the hour -> monotonically increasing seconds (unwrapping the hour)."""
    parts = minsec.str.strip().str.split("-", n=1, expand=True)
    s = parts[0].astype(float) * 60 + parts[1].astype(float)
    wraps = (s.diff() < -1800).cumsum()
    return s + wraps * 3600


def read(path: Path) -> tuple[pd.DataFrame, dict]:
    raw = pd.read_csv(path, skipinitialspace=True, low_memory=False)
    raw.columns = [c.strip() for c in raw.columns]
    for c in raw.columns:
        if raw[c].dtype == object or str(raw[c].dtype).startswith("str"):
            raw[c] = raw[c].astype("string").str.strip()

    t_log = _logger_seconds(raw["Min-Sec"])
    synced = raw["GPS_Synced"].str.lower().eq("true")
    gps = pd.to_datetime(raw["GPS_UTC"], utc=True, errors="coerce", format="ISO8601")
    offset = None
    if synced.any():
        gps_s = (gps[synced] - pd.Timestamp(0, tz="UTC")).dt.total_seconds()
        offset = float(np.median(gps_s - t_log[synced]))
    out = pd.DataFrame(index=raw.index)
    if offset is not None:
        out["time_utc"] = pd.to_datetime((t_log + offset) * 1e9, utc=True).dt.round("ms")
    else:
        out["time_utc"] = pd.NaT
    out["time_gps_utc"] = out["time_utc"]
    out["elapsed_s"] = (t_log - t_log.iloc[0]).round(3)
    out["sample_n"] = np.arange(len(raw))
    out["armed"] = pd.array([pd.NA] * len(raw), dtype="boolean")

    used = {"Min-Sec", "GPS_UTC"}
    missing = ["armed"]
    for name, (src, scale) in COLUMN_MAP.items():
        if src not in raw.columns:
            out[name] = np.nan
            missing.append(name)
            continue
        used.add(src)
        val = pd.to_numeric(raw[src], errors="coerce")
        out[name] = val if scale == 1 else (val * scale).round(6)

    # Before the first message of each kind arrives the logger writes exact zeros.
    imu = ["acc_x_m_s2", "acc_y_m_s2", "acc_z_m_s2"]
    no_imu = (out[imu] == 0).all(axis=1)
    out.loc[no_imu, [c for c in COLUMN_MAP if c.startswith(("acc_", "gyro_", "mag_", "roll", "pitch", "yaw"))]] = np.nan
    no_pm = out["batt_voltage_v"] == 0
    out.loc[no_pm, ["batt_voltage_v", "batt_current_a", "batt_consumed_mah", "batt_remaining_pct"]] = np.nan
    for c in ["lat_deg", "lon_deg", "gps_lat_deg", "gps_lon_deg"]:
        out.loc[out[c] == 0, c] = np.nan
    out["groundspeed_m_s"] = np.hypot(out["vel_n_m_s"], out["vel_e_m_s"]).round(3)
    out["climb_m_s"] = -out["vel_d_m_s"]
    out.loc[out["batt_remaining_pct"] < 0, "batt_remaining_pct"] = np.nan

    for c in FLIGHT_COLUMNS:
        if c not in out.columns:
            out[c] = np.nan
            missing.append(c)
    missing = [c for c in missing if c not in ("north_m", "east_m", "groundspeed_m_s", "climb_m_s")]
    extras = {c: raw[c] for c in raw.columns if c not in used}
    out = pd.concat([out, pd.DataFrame(extras, index=raw.index)], axis=1)
    out = out[list(FLIGHT_COLUMNS) + [c for c in out.columns if c not in FLIGHT_COLUMNS]]

    header = {
        "format": "early logger CSV (v1, no header block)",
        "format_version": "1",
        "gps_synced_from_row": int(synced.idxmax()) if synced.any() else None,
    }
    info = {
        "reader": NAME,
        "header": header,
        "gps_clock_offset_s": None,  # time_utc is already GPS-based
        "missing_columns": sorted(set(missing)),
        "raw_columns": list(raw.columns),
        "raw_hb_armed": None,
        "raw_rtc_utc": raw.get("RTC_UTC"),
        "notes": [
            "Header unit labels for IMU acc/gyro/mag and RawGPS_vel are wrong; converted using the MAVLink units.",
            "Battery_* columns come from a sensor that was not connected; PM_* (power module) is used instead.",
            "No heartbeat, flight mode, servo, vibration or EKF data in this log format.",
        ],
    }
    return out, info
