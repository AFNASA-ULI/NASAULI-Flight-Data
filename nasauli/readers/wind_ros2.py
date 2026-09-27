"""Reader for the wind-drone ROS 2 bag, via its CSV export.

Expected layout (next to the bag directory)::

    raw_data/<bag_name>_csv/wind_sensor_node__wind.csv
    raw_data/<bag_name>_csv/wind_sensor_node__temperature.csv

``bag_time_ns`` is when the wind-drone computer recorded the message; ``header.stamp`` is set by
the sensor node and is quantised to the sensor's 5 Hz output. Both are kept. ``vector.x`` is wind
speed and ``vector.y`` wind direction; ``vector.z`` has been 0 in every file so far.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

NAME = "wind_ros2_csv"
WIND_FILE = "wind_sensor_node__wind.csv"
TEMP_FILE = "wind_sensor_node__temperature.csv"


MCAP_MAGIC = b"\x89MCAP0\r\n"


def bag_closed(csv_dir: Path) -> bool | None:
    """Whether the bag this CSV was exported from was closed cleanly (MCAP files end with the magic bytes).

    A missing end marker means the recorder never finished the file (power loss, killed process, or a copy
    taken while it was still recording), so the recording may be longer than this file. None if no bag.
    """
    bag_dir = csv_dir.with_name(csv_dir.name.removesuffix("_csv"))
    files = sorted(bag_dir.glob("*.mcap"))
    if not files:
        return None
    for f in files:
        with open(f, "rb") as fh:
            fh.seek(max(0, f.stat().st_size - len(MCAP_MAGIC)))
            if fh.read() != MCAP_MAGIC:
                return False
    return True


def find(raw_dir: Path) -> list[Path]:
    return sorted(p.parent for p in raw_dir.glob(f"*/{WIND_FILE}"))


def read(csv_dir: Path) -> pd.DataFrame:
    w = pd.read_csv(csv_dir / WIND_FILE)
    df = pd.DataFrame(
        {
            "time_utc": pd.to_datetime(w["bag_time_ns"], unit="ns", utc=True),
            "sensor_stamp_utc": pd.to_datetime(
                w["header.stamp.sec"] * 1_000_000_000 + w["header.stamp.nanosec"], unit="ns", utc=True
            ),
            "wind_speed_m_s": w["vector.x"].astype(float),
            "wind_dir_deg": w["vector.y"].astype(float),
            "wind_z": w["vector.z"].astype(float),
        }
    )
    tpath = csv_dir / TEMP_FILE
    if tpath.exists():
        t = pd.read_csv(tpath)
        temp = pd.DataFrame(
            {
                "time_utc": pd.to_datetime(t["bag_time_ns"], unit="ns", utc=True),
                "temperature_c": t["temperature"].astype(float),
            }
        ).sort_values("time_utc")
        df = pd.merge_asof(
            df.sort_values("time_utc"), temp, on="time_utc", direction="nearest",
            tolerance=pd.Timedelta("1s"),
        )
    else:
        df["temperature_c"] = float("nan")
    return df.sort_values("time_utc").reset_index(drop=True)
