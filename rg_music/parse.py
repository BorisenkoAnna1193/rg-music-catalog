"""Step 2: parse the free-text music cell and normalise apparatus.

Usage:
    python -m rg_music.parse
Input:
    data/interim/routines_merged.csv         (python -m rg_music.merge: seasons expanded, competition
                                              tables merged; the *_raw.csv files are never modified)
    data/manual/music_overrides.csv          optional, typed by the owner: the tracks of a cell the rules
                                              cannot split (keyed by the cell text); they win over the rules
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
from rg_music.music_parser import Track, parse_music

INTERIM = Path("data/interim")

ROUTINE_FIELDS = [
    "routine_id", "gymnast_page", "year", "year_source", "apparatus", "variant", "context",
    "apparatus_raw", "music_raw", "music_kind", "n_tracks", "parse_status",
    "source", "notes", "source_url", "revid",
]
TRACK_FIELDS = [
    "routine_id", "track_no", "title", "work", "artist", "performer", "notes", "flags", "status", "raw_text",
]
_SEVERITY = {"ok": 0, "manual": 0, "partial": 1, "unparsed": 2}
OVERRIDES = Path("data/manual/music_overrides.csv")


def load_overrides(path: Path = OVERRIDES) -> dict[str, list[Track]]:
    """cell text -> tracks typed by the owner (columns raw_text, track_no, title, work, artist, ...)."""
    if not path.exists():
        return {}
    out: dict[str, list[Track]] = {}
    for r in sorted(csv.DictReader(path.open(encoding="utf-8-sig")), key=lambda r: (r["raw_text"], int(r["track_no"]))):
        out.setdefault(r["raw_text"], []).append(Track(
            raw_text=r["raw_text"], title=r["title"], work=r["work"], artist=r["artist"], performer=r["performer"],
            notes=[r["notes"]] if r["notes"] else [], flags=["manual_override"]))
    return out


def apply_overrides(tracks: list[Track], overrides: dict[str, list[Track]]) -> list[Track]:
    """Replace every rules track whose cell text has an override by the owner's tracks."""
    out: list[Track] = []
    done: set[str] = set()
    for t in tracks:
        if t.raw_text in overrides:
            if t.raw_text not in done:  # the rules may have produced several tracks from the same text
                out += overrides[t.raw_text]
                done.add(t.raw_text)
        else:
            out.append(t)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dir", type=Path, default=INTERIM)
    ap.add_argument("--overrides", type=Path, default=OVERRIDES)
    args = ap.parse_args(argv)
    overrides = load_overrides(args.overrides)

    rows = list(csv.DictReader((args.dir / "routines_merged.csv").open(encoding="utf-8")))
    routines, tracks = [], []
    for row in rows:
        rid = row["routine_id"]
        app = normalize_apparatus(row["apparatus"])
        kind, parsed = parse_music(row["music"])
        parsed = apply_overrides(parsed, overrides)
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
            "year_source": row["year_source"],
            "apparatus": app.apparatus, "variant": app.variant, "context": app.context,
            "apparatus_raw": row["apparatus"], "music_raw": row["music"], "music_kind": kind,
            "n_tracks": len(parsed), "parse_status": status,
            "source": row["source"],
            "notes": ";".join(filter(None, [row["notes"], *app.notes])),
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
