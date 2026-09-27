"""raw_data/ -> processed/ for each flight folder."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from . import __version__
from .checks import run_checks, summarize
from .clean import Session, find_flight_dirs, load_session, raw_logs
from .report import render
from .schema import FLIGHT_COLUMNS, WIND_COLUMNS

PROCESSED = "processed"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_table(df: pd.DataFrame, base: Path) -> None:
    df.to_parquet(base.with_suffix(".parquet"), index=False)
    csv = df.copy()
    for c in csv.columns:
        if isinstance(csv[c].dtype, pd.DatetimeTZDtype):
            csv[c] = csv[c].dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ").str[:-4] + "Z"
    csv.to_csv(base.with_suffix(".csv"), index=False)


def outputs_for(csv_path: Path) -> dict[str, Path]:
    out = csv_path.parent.parent / PROCESSED
    stem = csv_path.stem
    return {
        "flight": out / stem,  # .parquet and .csv
        "wind": out / f"{stem}_wind",  # .parquet and .csv
        "metadata": out / f"{stem}_metadata.json",
        "report": out / f"{stem}.html",
    }


def process_session(s: Session) -> dict:
    paths = outputs_for(s.source)
    paths["report"].parent.mkdir(parents=True, exist_ok=True)
    summary = summarize(s)
    checks = run_checks(s, summary)

    _write_table(s.flight, paths["flight"])
    downloads = {
        "flight data (Parquet)": paths["flight"].with_suffix(".parquet").name,
        "flight data (CSV)": paths["flight"].with_suffix(".csv").name,
    }
    if s.wind is not None:
        _write_table(s.wind, paths["wind"])
        downloads["wind data (Parquet)"] = paths["wind"].with_suffix(".parquet").name
        downloads["wind data (CSV)"] = paths["wind"].with_suffix(".csv").name
    downloads["metadata (JSON)"] = paths["metadata"].name

    header = {k: v for k, v in s.info["header"].items() if not k.startswith("_")}
    meta = {
        "pipeline_version": __version__,
        "reader": s.info["reader"],
        "source": {"file": s.source.name, "sha256": _sha256(s.source)},
        "header": header,
        "summary": summary,
        "checks": checks,
        "home": s.info["home"],
        "gps_clock_offset_s": s.info["gps_clock_offset_s"],
        "missing_columns": s.info["missing_columns"],
        "wind": s.wind_info or None,
        "columns": {k: {"unit": u, "description": d} for k, (u, d) in FLIGHT_COLUMNS.items()},
        "wind_columns": {k: {"unit": u, "description": d} for k, (u, d) in WIND_COLUMNS.items()}
        if s.wind is not None else None,
        "notes": "Columns not listed under 'columns' are raw logger columns carried through unchanged.",
    }
    paths["metadata"].write_text(json.dumps(meta, indent=2, default=str) + "\n")
    paths["report"].write_text(render(s, summary, checks, downloads))
    return meta


def process_flight_dir(flight_dir: Path, log=print) -> list[dict]:
    metas = []
    for csv_path in raw_logs(flight_dir):
        s = load_session(csv_path)
        if s is None:
            log(f"  skip {csv_path.name}: no reader for this format")
            continue
        meta = process_session(s)
        n_warn = sum(c["level"] == "warn" for c in meta["checks"])
        log(f"  {csv_path.name}: {len(s.flight)} rows, {n_warn} warning(s)"
            + (f", wind rows {s.wind_info['rows']}" if s.wind is not None else ""))
        metas.append(meta)
    return metas


def process_all(root: Path, log=print) -> None:
    for d in find_flight_dirs(root):
        log(d.name)
        process_flight_dir(d, log)
