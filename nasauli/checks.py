"""Flight summary numbers and data-quality checks, computed on the standard schema."""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

from .clean import Session
from .schema import FLIGHT_COLUMNS

AIRBORNE_ALT_M = 1.0
COMPASS_VAR_WARN = 0.5  # ArduPilot's default EKF failsafe threshold is 0.8
VIBE_WARN = 30.0  # m/s^2, ArduPilot's guidance for "too high"


def _r(x, n=1):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), n)


def mode_segments(df: pd.DataFrame) -> list[list]:
    m = pd.Series(df["flight_mode"].fillna("—").to_numpy(dtype=object), index=df.index)
    t = df["elapsed_s"]
    change = np.cumsum(m.to_numpy() != m.shift().to_numpy())
    segs = []
    for _, g in df.groupby(change, sort=True):
        segs.append([_r(t[g.index[0]], 2), _r(t[g.index[-1]], 2), m[g.index[0]]])
    for a, b in zip(segs, segs[1:]):
        a[1] = b[0]
    return segs


def summarize(s: Session) -> dict:
    df = s.flight
    t = df["elapsed_s"]
    air = df["armed"] & (df["alt_rel_m"] > AIRBORNE_ALT_M)
    out: dict = {
        "session_id": s.info["header"].get("session_id", s.stem),
        "platform": s.info["header"].get("platform_label") or s.info["header"].get("platform"),
        "start_utc": df["time_utc"].min().isoformat(),
        "end_utc": df["time_utc"].max().isoformat(),
        "duration_s": _r(t.max() - t.min()),
        "samples": int(len(df)),
        "sample_rate_hz": _r((len(df) - 1) / (t.max() - t.min()), 2) if len(df) > 1 else None,
        "modes": mode_segments(df),
    }
    if air.any():
        out["takeoff_s"] = _r(t[air].min())
        out["landing_s"] = _r(t[air].max())
        out["airborne_s"] = _r(t[air].max() - t[air].min())
        out["landed_in_log"] = bool(t[air].max() < t.max() - 1.0)
    out["max_alt_rel_m"] = _r(df["alt_rel_m"].max())
    rng = np.hypot(df["north_m"], df["east_m"])
    out["max_range_m"] = _r(rng.max(), 0)

    auto = df["flight_mode"].eq("AUTO")
    cruise = air & auto & (df["groundspeed_m_s"] > 2)
    if cruise.any():
        out["cruise_alt_m"] = _r(df.loc[cruise, "alt_rel_m"].median())
        out["cruise_speed_m_s"] = _r(df.loc[cruise, "groundspeed_m_s"].median())
        out["cruise_current_a"] = _r(df.loc[cruise, "batt_current_a"].median())
    seq = df.loc[auto & air, "mission_seq"].dropna()
    out["mission_items"] = int(seq[seq > 0].nunique()) if len(seq) else 0
    rtl = df.index[df["flight_mode"].eq("RTL") & (t > out.get("takeoff_s", -1))]
    out["rtl_s"] = _r(t[rtl[0]]) if len(rtl) else None

    mah = df["batt_consumed_mah"].dropna()
    out["batt_consumed_mah"] = _r(mah.max() - mah.min(), 0) if len(mah) else None
    rest_before = df.loc[~df["armed"] & (t < out.get("takeoff_s", t.max())), "batt_voltage_v"]
    rest_after = df.loc[~df["armed"] & (t > out.get("landing_s", t.max())), "batt_voltage_v"]
    out["batt_v_start"] = _r(rest_before.median(), 2) if len(rest_before) else _r(df["batt_voltage_v"].iloc[0], 2)
    out["batt_v_end"] = _r(rest_after.median(), 2) if len(rest_after) else _r(df["batt_voltage_v"].iloc[-1], 2)
    out["batt_v_end_at_rest"] = bool(len(rest_after))
    return out


def run_checks(s: Session, summary: dict) -> list[dict]:
    """Return a list of {"level": "warn"|"info", "title", "detail"} findings."""
    df, info, h = s.flight, s.info, s.info["header"]
    found: list[dict] = []

    def add(level, title, detail):
        found.append({"level": level, "title": title, "detail": detail})

    # --- wind sensor overlap
    if s.wind is None:
        add("info", "No wind-drone log", "No wind sensor data was found in this flight's raw_data folder.")
    else:
        w = s.wind_info
        if w["rows"] == 0:
            add("warn", "Wind log doesn't overlap this flight",
                f"The wind log covers {w['wind_log_start_utc'][11:19]}–{w['wind_log_end_utc'][11:19]} UTC; "
                f"this flight runs {w['flight_start_gps_utc'][11:19]}–{w['flight_end_gps_utc'][11:19]} UTC (GPS time).")
        elif w["coverage_pct"] < 99:
            add("warn", "Wind log only partly overlaps this flight",
                f"It covers {w['coverage_pct']}% of the flight.")

    # --- clocks
    off = info.get("gps_clock_offset_s")
    if h.get("chrony_synchronised", "").lower() == "false":
        add("warn", "Logger clock not synchronised",
            "The header says chrony_synchronised: False"
            + (f"; the host clock is {abs(off):.2f} s {'behind' if off > 0 else 'ahead of'} the autopilot's GPS time. "
               "time_gps_utc corrects for this." if off is not None else "."))
    rtc = info.get("raw_rtc_utc")
    if rtc is not None and rtc.notna().any():
        first = str(rtc.dropna().iloc[0])
        parsed = pd.to_datetime(first, errors="coerce", utc=True)
        start = df["time_utc"].min()
        if pd.notna(parsed) and abs((parsed - start).total_seconds()) > 86400:
            add("warn", "Real-time clock (RTC) not set",
                f"RTC_UTC reads {first}, but the flight is on {start.date()}.")
    spreadsheet = []
    if h.get("_trailing_commas"):
        spreadsheet.append("the # header lines end in runs of commas")
    if rtc is not None and rtc.notna().any() and not re.match(r"^\d{4}-\d{2}-\d{2}", str(rtc.dropna().iloc[0])):
        spreadsheet.append(f"RTC_UTC reads “{rtc.dropna().iloc[0]}” instead of an ISO date")
    if spreadsheet:
        add("warn", "Raw file looks re-saved by a spreadsheet program",
            "; ".join(spreadsheet)[0].upper() + "; ".join(spreadsheet)[1:] + ". Excel does both when it re-saves a "
            "CSV, and it can also round values. Compare with the original file from the logger.")

    # --- session id vs start time
    sid = h.get("session_id", "")
    m = re.search(r"(\d{8})T(\d{6})Z", sid)
    if m and h.get("start_utc", "")[:10].replace("-", "") != m.group(1):
        add("warn", "Session ID date doesn't match the start time",
            f"session_id is {sid}, but start_utc is {h.get('start_utc')}. The logger probably reused an old session ID.")

    # --- heartbeat mixing
    hb = info.get("raw_hb_armed")
    if hb is not None:
        raw_toggles = int(hb.dropna().diff().abs().sum())
        clean_toggles = int(df["armed"].astype(int).diff().abs().sum())
        if raw_toggles > 4 * max(clean_toggles, 1):
            add("info", "HB_Armed mixes heartbeats from several MAVLink components",
                f"The raw HB_Armed column flips {raw_toggles} times. The cleaned armed column only uses autopilot "
                f"heartbeats (base_mode bit 0 set) and changes {clean_toggles} time{'s' if clean_toggles != 1 else ''}. The logger should filter "
                "heartbeats to the autopilot's sysid/compid.")

    # --- unit labels
    if any(c.endswith("mag_mT") for c in info["raw_columns"]):
        add("info", "Magnetometer columns mislabelled",
            "IMU_*mag_mT holds MAVLink SCALED_IMU values, which are milligauss (Earth's field is ≈500 mG, ≈0.05 mT). "
            "The cleaned data calls them mag_*_mgauss; the logger's column names should be fixed.")

    # --- landing in log
    if summary.get("takeoff_s") is not None and not summary.get("landed_in_log", True):
        add("info", "Log ends while airborne", "The log stops before the vehicle landed.")

    # --- empty / constant columns (raw columns kept in the cleaned data)
    raw_cols = [c for c in info["raw_columns"] if c in df.columns]
    empty = [c for c in raw_cols if df[c].isna().all()]
    mapped_empty = [c for c in FLIGHT_COLUMNS if df[c].isna().all() and c not in info["missing_columns"]]
    if empty or mapped_empty:
        cols = empty + mapped_empty
        add("info", "Empty columns", f"{len(cols)} column(s) have no data: " + ", ".join(cols[:30])
            + (" …" if len(cols) > 30 else ""))
    wind_ap = df[["ap_wind_speed_m_s", "ap_wind_dir_deg"]].dropna()
    if len(wind_ap) and wind_ap.nunique().max() <= 1:
        add("info", "Autopilot wind estimate is constant",
            f"WND_* stays at speed {wind_ap.iloc[0, 0]}, direction {wind_ap.iloc[0, 1]} for the whole log.")

    # --- EKF / vibration / GPS
    cv = df["ekf_compass_var"].max()
    if pd.notna(cv) and cv >= COMPASS_VAR_WARN:
        t = df.loc[df["ekf_compass_var"].idxmax(), "elapsed_s"]
        add("warn", "High compass variance",
            f"EKF compass variance peaks at {cv:.2f} (t = {t:.1f} s). ArduPilot's default failsafe threshold is 0.8.")
    vmax = df[["vib_x_m_s2", "vib_y_m_s2", "vib_z_m_s2"]].max().max()
    if pd.notna(vmax) and vmax >= VIBE_WARN:
        add("warn", "High vibration", f"Peak vibration is {vmax:.1f} m/s² (guidance: keep below {VIBE_WARN:.0f}).")
    clips = df[["clip_0", "clip_1", "clip_2"]].max() - df[["clip_0", "clip_1", "clip_2"]].min()
    if clips.fillna(0).sum() > 0:
        add("warn", "Accelerometer clipping", "Clip counters increased during the log: "
            + ", ".join(f"{k} +{int(v)}" for k, v in clips.items() if v > 0))
    air = df["armed"] & (df["alt_rel_m"] > AIRBORNE_ALT_M)
    if air.any():
        sats = df.loc[air, "gps_sats"].min()
        hdop = df.loc[air, "gps_hdop"].max()
        if (pd.notna(sats) and sats < 8) or (pd.notna(hdop) and hdop > 1.5):
            add("warn", "Weak GPS in flight", f"Minimum {sats:.0f} satellites, maximum HDOP {hdop:.2f} while airborne.")

    # --- logger timing
    if "Slots_Skipped" in df.columns:
        skipped = pd.to_numeric(df["Slots_Skipped"], errors="coerce").sum()
        if skipped > 0:
            add("info", "Logger skipped samples", f"{int(skipped)} scheduled sample slot(s) were skipped.")

    order = {"warn": 0, "info": 1}
    return sorted(found, key=lambda f: order[f["level"]])
