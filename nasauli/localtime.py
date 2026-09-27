"""Local time for display. The flights are flown in Colorado, so the website and reports show Mountain Time
(MST/MDT, with daylight saving handled by the tz database). The data files keep UTC columns as well.
"""

from __future__ import annotations

import pandas as pd

LOCAL_TZ = "America/Denver"
LOCAL_LABEL = "MT"  # short name for column headers; individual times show MDT or MST


def to_local(t) -> pd.Timestamp:
    """A UTC timestamp or ISO string -> Mountain Time."""
    t = pd.Timestamp(t)
    if t.tzinfo is None:
        t = t.tz_localize("UTC")
    return t.tz_convert(LOCAL_TZ)


def fmt(t, pattern: str = "%d %b %Y · %H:%M %Z") -> str:
    return to_local(t).strftime(pattern)


def series_to_local(s: pd.Series) -> pd.Series:
    return s.dt.tz_convert(LOCAL_TZ)
