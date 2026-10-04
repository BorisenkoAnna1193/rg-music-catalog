"""Merge the two music sources of a gymnast page into one list of routines.

Inputs (data/interim, never modified):
    routines_raw.csv       "Year / Apparatus / Music" tables
    competitions_raw.csv   competition tables (e.g. Olympics) that also have a Music column
Outputs:
    routines_merged.csv    one row per routine and year
    routine_events.csv     competitions where a routine was performed (many per routine)
    merge_report.json      what was merged, added, expanded, skipped

Rules (decided with the owner):
  * A season "2022/2023" means the same music was used in both years: the row is expanded into
    one row per year that differ only by the year (id ...#2022, ...#2023, flag expanded_from_season).
  * A competition row with the same gymnast, apparatus, a year within +-1 and similar music
    (>= FUZZY_OK) is the same routine: it is not added, the competition becomes an event of that
    routine (source "both"). A routine can have several events: the same music is often used at
    several competitions in a season.
  * Otherwise the competition row becomes a new routine (source "competition_table"); when the
    routine table has other music for that apparatus and year, the new row is flagged
    differs_from_routine_table so that conflicts are visible, not silently resolved.
  * Competition rows without music, or without a single apparatus (all-around), only describe
    participation and are skipped.

Usage:
    python -m rg_music.merge
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

from rg_music.apparatus import normalize_apparatus
from rg_music.crosscheck import FUZZY_OK, norm_music, similarity
from rg_music.music_parser import parse_music
from rg_music.years import expand_years, parse_years

INTERIM = Path("data/interim")
MERGED_FIELDS = ["routine_id", "gymnast_page", "table_index", "row_index", "year", "year_source", "apparatus",
                 "music", "source", "notes", "source_url", "revid"]
EVENT_FIELDS = ["routine_id", "competition", "location", "event_year", "source_row"]


def music_score(a: str, b: str) -> float:
    """Similarity of two music cells: the whole text, or the best pair of track titles.

    Comparing titles as well keeps "Avrora by X" and "music from Avrora by X", or one track of a
    three-track cell, from looking like different music. A title that sits whole inside the
    other ("Nur kein genieren" / "Nur kein genieren from Elisabeth") counts as the same.
    """
    best = similarity(a, b)
    names = lambda cell: [n for t in parse_music(cell)[1] for n in (t.title, t.work) if n]  # noqa: E731
    titles_a, titles_b = names(a), names(b)
    for x in titles_a:
        for y in titles_b:
            nx, ny = norm_music(x), norm_music(y)
            contained = min(len(nx), len(ny)) >= 4 and (f" {nx} " in f" {ny} " or f" {ny} " in f" {nx} ")
            best = max(best, similarity(x, y), 0.9 if contained else 0.0)
    return best


def _base_id(row: dict, prefix: str = "") -> str:
    return f"{row['gymnast_page']}|{prefix}{row['table_index']}|{row['row_index']}"


def expand_routines(rows: list[dict]) -> list[dict]:
    """One row per year; a season row becomes several rows that differ only by year."""
    out = []
    for r in rows:
        years = expand_years(r["year"])
        base = _base_id(r)
        notes = [n for n in r["notes"].split(";") if n and not (years and n == "year_not_a_year")]
        for y in years or [None]:
            seasonal = len(years) > 1
            out.append({
                "routine_id": f"{base}#{y}" if seasonal else base,
                "gymnast_page": r["gymnast_page"], "table_index": r["table_index"], "row_index": r["row_index"],
                "year": y if y is not None else r["year"],
                "year_source": r["year"] if seasonal else "",
                "apparatus": r["apparatus"], "music": r["music"], "source": "routine_table",
                "notes": ";".join(notes + (["expanded_from_season"] if seasonal else []) +
                                  (["year_unreadable"] if y is None else [])),
                "source_url": r["source_url"], "revid": r["revid"],
            })
    return out


def merge_sources(routines: list[dict], competitions: list[dict]) -> tuple[list[dict], list[dict], dict]:
    merged = expand_routines(routines)
    events: list[dict] = []
    seen_events: set[tuple] = set()
    stats = Counter(seasons_expanded=len(merged) - len(routines))

    def add_event(routine_id: str, c: dict, year: int) -> None:
        key = (routine_id, c["competition"], c["location"], year)
        if key not in seen_events:
            seen_events.add(key)
            events.append({"routine_id": routine_id, "competition": c["competition"], "location": c["location"],
                           "event_year": year, "source_row": _base_id(c, "c")})

    by_gymnast: dict[str, list[dict]] = {}
    for m in merged:
        by_gymnast.setdefault(m["gymnast_page"], []).append(m)

    for c in competitions:
        span = parse_years(c["year"])
        app = normalize_apparatus(c["apparatus"]).apparatus
        if not c["music"] or not app or span is None:
            stats["competition_rows_skipped"] += 1
            continue
        year = span[0]
        pool = [m for m in by_gymnast.setdefault(c["gymnast_page"], [])
                if m["music"] and normalize_apparatus(m["apparatus"]).apparatus == app and isinstance(m["year"], int)]
        near = [(music_score(c["music"], m["music"]), -abs(m["year"] - year), m) for m in pool if abs(m["year"] - year) <= 1]
        best = max(near, key=lambda t: (t[0], t[1]), default=None)
        if best and best[0] >= FUZZY_OK:
            m = best[2]
            m["source"] = "both" if m["source"] == "routine_table" else m["source"]
            if m["year"] != year:
                m["notes"] = ";".join(filter(None, [m["notes"], "event_year_differs"]))
            add_event(m["routine_id"], c, year)
            stats["competition_rows_merged"] += 1
            continue
        new = {
            "routine_id": _base_id(c, "c"), "gymnast_page": c["gymnast_page"], "table_index": c["table_index"],
            "row_index": c["row_index"], "year": year, "year_source": "", "apparatus": c["apparatus"],
            "music": c["music"], "source": "competition_table",
            "notes": ";".join(filter(None, [c["notes"],
                              "differs_from_routine_table" if any(m["year"] == year for m in pool) else ""])),
            "source_url": c["source_url"], "revid": c["revid"],
        }
        merged.append(new)
        by_gymnast[c["gymnast_page"]].append(new)
        add_event(new["routine_id"], c, year)
        stats["competition_rows_added"] += 1
        stats["added_with_conflict"] += "differs_from_routine_table" in new["notes"]

    merged.sort(key=lambda m: (m["gymnast_page"], m["year"] if isinstance(m["year"], int) else 0,
                               m["apparatus"], m["routine_id"]))
    return merged, events, dict(stats)


def _write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dir", type=Path, default=INTERIM)
    args = ap.parse_args(argv)

    read = lambda name: list(csv.DictReader((args.dir / name).open(encoding="utf-8")))  # noqa: E731
    routines, competitions = read("routines_raw.csv"), read("competitions_raw.csv")
    merged, events, stats = merge_sources(routines, competitions)

    _write_csv(args.dir / "routines_merged.csv", MERGED_FIELDS, merged)
    _write_csv(args.dir / "routine_events.csv", EVENT_FIELDS, events)
    stats.update(routines_in=len(routines), competition_rows_in=len(competitions), routines_out=len(merged),
                 events=len(events), by_source=dict(Counter(m["source"] for m in merged)))
    (args.dir / "merge_report.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
