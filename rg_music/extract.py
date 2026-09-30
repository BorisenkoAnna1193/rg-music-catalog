"""Step 1: download gymnast articles and dump their music tables as-is.

Usage:
    python -m rg_music.extract                      # seed list, cached pages
    python -m rg_music.extract --refresh            # re-download everything
    python -m rg_music.extract --titles "Dina Averina" "Linoy Ashram"

Outputs (nothing is normalised yet - that is step 2):
    data/interim/routines_raw.csv       one row per routine-table row
    data/interim/competitions_raw.csv   rows of competition tables with music
    data/interim/extract_report.json    what was found on every page
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from pathlib import Path

from .events import normalize_event
from .tables import extract_music_tables
from .wiki_client import WikiClient, WikiError

FIELDS = [
    "gymnast_page", "requested_title", "revid", "table_index", "row_index",
    "year", "apparatus", "music", "competition", "location", "notes", "source_url",
]


def read_titles(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=Path, default=Path("data/seed_gymnasts.txt"))
    ap.add_argument("--titles", nargs="*", help="article titles (overrides --seed)")
    ap.add_argument("--out", type=Path, default=Path("data/interim"))
    ap.add_argument("--cache", type=Path, default=Path("data/raw"))
    ap.add_argument("--refresh", action="store_true", help="ignore the HTML cache")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    titles = args.titles or read_titles(args.seed)
    client = WikiClient(cache_dir=args.cache)
    args.out.mkdir(parents=True, exist_ok=True)

    routine_rows, comp_rows, report = [], [], []
    for title in titles:
        entry = {"requested_title": title}
        try:
            page = client.get_page(title, refresh=args.refresh)
        except (WikiError, Exception) as exc:  # keep going, record the failure
            logging.error("failed: %s: %s", title, exc)
            entry["error"] = str(exc)
            report.append(entry)
            continue

        infos, rows = extract_music_tables(page.html)
        entry.update(
            page=page.title,
            redirected=page.title != title,
            revid=page.revid,
            tables=[i.__dict__ for i in infos if i.kind != "other"],
            other_tables=len([i for i in infos if i.kind == "other"]),
            routine_rows=sum(r.table_kind == "routine" for r in rows),
            competition_rows=sum(r.table_kind == "competition" for r in rows),
            rows_with_notes=sum(bool(r.notes) for r in rows),
        )
        report.append(entry)

        for r in rows:
            if r.table_kind == "competition":
                r.competition, r.year, event_notes = normalize_event(r.competition, r.location, r.year)
                r.notes.extend(event_notes)
            rec = {
                "gymnast_page": page.title,
                "requested_title": title,
                "revid": page.revid,
                "table_index": r.table_index,
                "row_index": r.row_index,
                "year": r.year,
                "apparatus": r.apparatus,
                "music": r.music,
                "competition": r.competition,
                "location": r.location,
                "notes": ";".join(r.notes),
                "source_url": page.url,
            }
            (routine_rows if r.table_kind == "routine" else comp_rows).append(rec)

    _write_csv(args.out / "routines_raw.csv", routine_rows)
    _write_csv(args.out / "competitions_raw.csv", comp_rows)
    (args.out / "extract_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _print_summary(report)
    return 0 if all("error" not in e for e in report) else 1


def _write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def _print_summary(report: list[dict]) -> None:
    print(f"\n{'page':32} {'routine':>8} {'compet.':>8} {'notes':>6}  status")
    for e in report:
        if "error" in e:
            print(f"{e['requested_title']:32} {'':>8} {'':>8} {'':>6}  ERROR {e['error'][:40]}")
            continue
        status = "ok" if e["routine_rows"] else "NO ROUTINE TABLE"
        if e["redirected"]:
            status += f" (redirect from '{e['requested_title']}')"
        print(f"{e['page']:32} {e['routine_rows']:>8} {e['competition_rows']:>8} "
              f"{e['rows_with_notes']:>6}  {status}")
    total = sum(e.get("routine_rows", 0) for e in report)
    print(f"\n{total} routine rows from {len(report)} pages")


if __name__ == "__main__":
    sys.exit(main())
