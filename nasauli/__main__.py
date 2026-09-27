"""Command line: ``python -m nasauli process [FLIGHT_DIR ...]`` and ``python -m nasauli site``."""

from __future__ import annotations

import argparse
from pathlib import Path

from . import __version__
from .pipeline import process_all, process_flight_dir
from .site import build_site


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="python -m nasauli", description=__doc__)
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("process", help="raw_data/ -> processed/ (Parquet, CSV, JSON, HTML report)")
    p.add_argument("flight_dirs", nargs="*", type=Path, help="flight folders (default: all)")
    p.add_argument("--root", type=Path, default=Path("."), help="repository root")
    s = sub.add_parser("site", help="build the static website from processed/ folders")
    s.add_argument("--root", type=Path, default=Path("."))
    s.add_argument("--out", type=Path, default=Path("_site"))
    args = ap.parse_args(argv)

    if args.cmd == "process":
        if args.flight_dirs:
            for d in args.flight_dirs:
                print(d.name)
                process_flight_dir(d)
        else:
            process_all(args.root)
    elif args.cmd == "site":
        n = build_site(args.root, args.out)
        print(f"wrote {args.out}/index.html ({n} entries)")


if __name__ == "__main__":
    main()
