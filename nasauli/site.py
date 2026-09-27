"""Build the static website (GitHub Pages) from the processed/ folders."""

from __future__ import annotations

import html
import json
import shutil
from pathlib import Path

from . import __version__
from .clean import find_flight_dirs, raw_logs
from .pipeline import PROCESSED

REPO_URL = "https://github.com/AFNASA-ULI/NASAULI-Flight-Data"


def build_site(root: Path, out: Path) -> int:
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    rows = []
    for d in find_flight_dirs(root):
        metas = sorted((d / PROCESSED).glob("*_metadata.json"))
        if not metas:
            files = ", ".join(p.name for p in raw_logs(d)) or "no CSV"
            rows.append((d.name, "", f'<tr><td><a href="{REPO_URL}/tree/main/{d.name}">{html.escape(d.name)}</a></td>'
                         f'<td colspan="5" class="muted">Raw data only ({html.escape(files)}); '
                         'this log format has no reader yet.</td></tr>'))
            continue
        shutil.copytree(d / PROCESSED, out / d.name)
        for m in metas:
            meta = json.loads(m.read_text())
            sm = meta["summary"]
            stem = m.name[: -len("_metadata.json")]
            n_warn = sum(c["level"] == "warn" for c in meta["checks"])
            w = meta.get("wind")
            wind = "–" if not w else (f"{w['coverage_pct']:.0f}%" if w["rows"] else "no overlap")
            rng = f"{sm['max_range_m']:.0f} m" if sm.get("max_range_m") is not None else "–"
            air = f"{sm['airborne_s']:.0f} s" if sm.get("airborne_s") is not None else "–"
            rows.append((d.name, sm["start_utc"], (
                f'<tr><td><a href="{d.name}/{stem}.html">{html.escape(sm["start_utc"][:16].replace("T", " "))} UTC</a>'
                f'<div class="muted">{html.escape(d.name)}</div></td>'
                f'<td>{html.escape(sm.get("platform") or "")}</td>'
                f'<td>{air}</td><td>{rng}</td><td>{wind}</td>'
                f'<td>{n_warn}</td></tr>')))
    rows.sort(key=lambda r: (r[1] or "0", r[0]), reverse=True)
    (out / "index.html").write_text(INDEX.replace("__ROWS__", "\n".join(r[2] for r in rows))
                                    .replace("__REPO__", REPO_URL).replace("__VERSION__", __version__))
    (out / ".nojekyll").write_text("")
    return len(rows)


INDEX = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NASA ULI Flight Data</title>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root{--bg:#EEF2F5;--panel:#FFFFFF;--ink:#1C2733;--muted:#5B6B7B;--rule:#C9D3DC;--c1:#2F6690}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#141A21;--panel:#1B232C;--ink:#DCE3EA;--muted:#8C9AA8;--rule:#2E3945;--c1:#6FA8D6}}
:root[data-theme="dark"]{--bg:#141A21;--panel:#1B232C;--ink:#DCE3EA;--muted:#8C9AA8;--rule:#2E3945;--c1:#6FA8D6}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 "IBM Plex Sans",system-ui,sans-serif;font-variant-numeric:tabular-nums}
main{max-width:1000px;margin:0 auto;padding:28px 16px 48px}
h1{font-size:1.6rem;font-weight:600;margin:0 0 4px}
p{color:var(--muted);max-width:75ch}
a{color:var(--c1)}
.wrap{overflow-x:auto;background:var(--panel);border:1px solid var(--rule);border-radius:4px}
table{border-collapse:collapse;width:100%}
th,td{text-align:left;padding:8px 12px;border-bottom:1px solid var(--rule);vertical-align:top}
th{font-weight:600;font-size:.85rem;color:var(--muted)}
tr:last-child td{border-bottom:0}
.muted{color:var(--muted);font-size:.85rem}
</style>
</head>
<body>
<main>
<h1>NASA ULI Flight Data</h1>
<p>Flight logs from the NASA University Leadership Initiative data collection. Each report shows the flight
interactively, lists data-quality findings, and links to the cleaned data (Parquet and CSV) and its metadata.
Raw logs are in the <a href="__REPO__">GitHub repository</a>.</p>
<div class="wrap"><table>
<thead><tr><th>Flight</th><th>Platform</th><th>Airborne</th><th>Max range</th><th>Wind sensor</th><th>Warnings</th></tr></thead>
<tbody>
__ROWS__
</tbody></table></div>
<p class="muted">Built by the nasauli pipeline v__VERSION__.</p>
</main>
</body>
</html>
"""
