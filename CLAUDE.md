# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository purpose

This is a **data repository**, not a codebase. It stores flight telemetry logs collected from a Tarot 450
quadcopter as part of the NASA ULI (University Leadership Initiative) data collection effort. There is no
application code, build system, linter, or test suite here — do not invent one. Work in this repo consists
of adding, renaming, organizing, or reviewing/fixing CSV/XLSX flight-log data.

Logs are offloaded from an onboard Raspberry Pi (`cubelink/pizero2`) that runs the logger and streams
telemetry over MAVLink from the flight controller.

## Directory/naming conventions

Each flight session lives in its own top-level folder. Two naming schemes exist in history:

- `Tarot450_<UTC session folder timestamp>` (current), e.g. `Tarot450_20260925_165053Z`
- Bare UTC timestamp folders (older/retired), e.g. `20260923_154237Z`

Inside a session folder, the CSV filename typically encodes the actual session start time, e.g.
`TAROT_450_20260925T165912Z.csv`, which usually differs from the folder's timestamp (folder = when the
file was offloaded/downloaded; filename = when the session/recording started).

A folder may also contain an `offload_manifest_<timestamp>.json` describing the download/verification
(source host/path, file size, sha256 checksum match) from when the file was pulled off the Pi — treat this
as provenance metadata for the CSV(s) in the same folder, not something to edit.

A `_Fixed.csv` / `_Fixed.xlsx` file alongside a raw CSV (see `Tarot450_20260408/`) is a cleaned/corrected
version of the same session (e.g. reformatted numeric fields) — do not assume it is a from-scratch export;
diff against the original before making further edits.

## Data formats

There are two generations of log schema present in this repo; check the file before assuming a layout.

**v1 (older, e.g. `Tarot450_20260408/*.csv`)**: no header preamble, comma-separated columns start on line 1
directly with a header row (`Min-Sec, RTC_UTC, GPS_UTC, GPS_Synced, Battery_Temp_C, ...`). Values are often
padded with spaces for alignment. Column groups: `Battery_*`, `PM_*` (power module), `IMU_*` (roll/pitch/yaw,
rates, accel, gyro, mag), `RawGPS_*`, `FusedGPS_*`.

**v2 (current, "nasauli session log v2.0.0", e.g. `Tarot450_2026092*` folders)**: file begins with a block of
`# key: value` comment lines (session_id, platform, mode, start_utc, sample_rate_hz_target, operator,
location, factorial_condition, replicate, commanded_altitude_m/speed_ms, sensor-enabled flags, time-sync/chrony
info, hostname, mavlink connection info) terminated by a `# ---` line, followed by the real CSV header and
data rows. Column groups map to MAVLink message types: `HB_*` (heartbeat), `ATT_*` (attitude), `IMU_*`,
`RIMU_*` (raw IMU), `GPS_*`/`POS_*`, `SYST_*`, `BAT_*`/`SYS_*`/`PWR_*` (power), `ESC*_*`, `VFR_*`, `SRV*_us`
(servo outputs), `RC*_us` (RC input), `NAV_*`, `MIS_*` (mission), `VIB_*` (vibration), `EKF_*`, `BARO_*`,
`WND_*` (wind), plus `MAV_FlightMode`. Each `*_rx_UTC`/`*_Age_ms` pair records when that MAVLink message was
last received and how stale it was relative to the sample row.

When editing or generating v2 CSVs, preserve the `# ---`-delimited metadata preamble — downstream tooling
(outside this repo) may rely on it to identify session config, not just the column header row.

## Working in this repo

- Prefer keeping raw/original offloaded files untouched; put corrections in a new `_Fixed` file next to the
  original rather than overwriting it, matching existing convention.
- Session folders and manifests double as a chain-of-custody record (checksums, source path/host); don't
  delete or rewrite manifest JSON files casually.
- There is no CI, build, or test command to run after changes — validation here means confirming the CSV
  parses correctly and column counts/order match the header row.
