"""Step 2: parse the free-text music cell and normalise apparatus.

Usage:
    python -m rg_music.parse
Input:
    data/interim/routines_raw.csv            (never modified)
Output:
    data/interim/routines_parsed.csv         one row per routine
    data/interim/tracks.csv                  one row per track, keyed by routine_id
    data/interim/parse_report.json           coverage and the rows rules could not parse
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

from rg_music.apparatus import normalize_apparatus
from rg_music.music_parser import parse_music
from rg_music.years import parse_years

INTERIM = Path("data/interim")

ROUTINE_FIELDS = [
    "routine_id", "gymnast_page", "year", "year_from", "year_to", "apparatus", "variant", "context",
    "apparatus_raw", "music_raw", "music_kind", "n_tracks", "parse_status",
    "competition", "location", "notes", "source_url", "revid",
]
TRACK_FIELDS = [
    "routine_id", "track_no", "title", "work", "artist", "performer", "notes", "flags", "status", "raw_text",
]
_SEVERITY = {"ok": 0, "partial": 1, "unparsed": 2}


def routine_id(row: dict) -> str:
    return f"{row['gymnast_page']}|{row['table_index']}|{row['row_index']}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dir", type=Path, default=INTERIM)
    args = ap.parse_args(argv)

    rows = list(csv.DictReader((args.dir / "routines_raw.csv").open(encoding="utf-8")))
    routines, tracks = [], []
    for row in rows:
        rid = routine_id(row)
        app = normalize_apparatus(row["apparatus"])
        kind, parsed = parse_music(row["music"])
        years = parse_years(row["year"])
        for n, t in enumerate(parsed, 1):
            tracks.append({
                "routine_id": rid, "track_no": n, "title": t.title, "work": t.work,
                "artist": t.artist, "performer": t.performer, "notes": "; ".join(t.notes),
                "flags": ";".join(dict.fromkeys(t.flags)),
                "status": "reference" if kind == "reference" else t.status,
                "raw_text": t.raw_text,
            })
        status = kind if kind != "tracks" else max(
            (t.status for t in parsed), key=_SEVERITY.__getitem__
        )
        routines.append({
            "routine_id": rid, "gymnast_page": row["gymnast_page"], "year": row["year"],
            "year_from": years[0] if years else "", "year_to": years[1] if years else "",
            "apparatus": app.apparatus, "variant": app.variant, "context": app.context,
            "apparatus_raw": row["apparatus"], "music_raw": row["music"], "music_kind": kind,
            "n_tracks": len(parsed), "parse_status": status,
            "competition": row["competition"], "location": row["location"],
            "notes": ";".join(filter(None, [row["notes"], *app.notes,
                                            "season_range" if years and years[0] != years[1] else "",
                                            "year_unreadable" if not years else ""])),
            "source_url": row["source_url"], "revid": row["revid"],
        })

    _write_csv(args.dir / "routines_parsed.csv", ROUTINE_FIELDS, routines)
    _write_csv(args.dir / "tracks.csv", TRACK_FIELDS, tracks)
    report = _report(routines, tracks)
    (args.dir / "parse_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _print_summary(report)
    return 0


def _write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def _report(routines: list[dict], tracks: list[dict]) -> dict:
    return {
        "routines": len(routines),
        "routine_status": Counter(r["parse_status"] for r in routines),
        "tracks": len(tracks),
        "track_status": Counter(t["status"] for t in tracks),
        "flags": Counter(f for t in tracks for f in t["flags"].split(";") if f),
        "unknown_apparatus": [r["apparatus_raw"] for r in routines if not r["apparatus"]],
        "unparsed": [t["raw_text"] for t in tracks if t["status"] == "unparsed"],
    }


def _print_summary(report: dict) -> None:
    print(f"{report['routines']} routines -> {report['tracks']} tracks")
    print("routines:", dict(report["routine_status"]))
    print("tracks:  ", dict(report["track_status"]))
    print("flags:   ", dict(report["flags"]))
    if report["unknown_apparatus"]:
        print("unknown apparatus:", report["unknown_apparatus"])


if __name__ == "__main__":
    sys.exit(main())
