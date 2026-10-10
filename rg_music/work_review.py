"""Review sheet for the titles that are still split by credit after the MusicBrainz joins (for the owner).

One row per track: title, group letter, the MusicBrainz evidence of the group, gymnast, year, apparatus and the music
cell as Wikipedia has it. Within a title the groups are lettered A, B, C... (A = the biggest; a group joined by
MusicBrainz is one letter). `decision` is pre-filled with the row's own letter: the owner changes it to the letter
of the group the track really belongs to (B -> A = "this is the same song as A"); an unchanged letter keeps it apart.
`owner_note` is free text. Titles are sorted by the number of gymnasts, the most used first. `row_id` numbers the
rows: the owner edits a Google Sheets copy without the technical columns, and decisions come back by row_id.

The sheet is never overwritten once it exists (the owner types into it): pass --force to rebuild it.

The owner fills it in Google Sheets (Drive folder rg_music). --import reads that sheet, exported as CSV, and writes
the owner's decisions to data/manual/work_review_decisions.csv: one row per split group whose letter changed
(join_to = a split_key of the target group) or that has a note. works.py --resolve applies them. Groups are keyed
by split_key ("<title> ~ <main credit>"), which comes from the credits, so the decisions survive a rerun.

Usage:
    python -m rg_music.work_review [--force]
    python -m rg_music.work_review --import <sheet exported as csv>
Reads  data/interim/track_works.csv, routines_parsed.csv, tracks.csv, work_mb_links.csv
Writes data/interim/work_split_review.csv (utf-8 with BOM), or data/manual/work_review_decisions.csv with --import
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path
from string import ascii_uppercase

INTERIM = Path("data/interim")
DECISIONS = Path("data/manual/work_review_decisions.csv")
DECISION_FIELDS = ["title_cluster", "split_key", "join_to", "owner_note", "source"]
FIELDS = ["row_id", "title_no", "title", "title_gymnasts", "group", "evidence", "gymnast", "year", "apparatus", "source_text",
          "decision", "owner_note", "work_key", "routine_id", "track_no"]


def evidence_of(work_key: str, rows: list[dict], links: dict[str, dict]) -> str:
    if work_key.endswith("~ no credit"):
        return "no credit"
    found = [links[r["split_key"]] for r in rows if links.get(r["split_key"], {}).get("mb_work_id")]
    if not found:
        return "none"
    return f"MusicBrainz: {found[0]['mb_writers']}" if found[0]["mb_writers"] else "MusicBrainz"


def build_review(track_works: list[dict], routines: dict[str, dict], cells: dict[tuple, str],
                 links: dict[str, dict]) -> list[dict]:
    by: dict[str, list[dict]] = defaultdict(list)
    for t in track_works:
        if t["split_key"]:
            by[t["title_cluster"]].append(t)
    gymnasts = lambda rs: len({routines[r["routine_id"]]["gymnast_page"] for r in rs})  # noqa: E731
    open_titles = [(c, rs) for c, rs in by.items() if len({r["work_key"] for r in rs}) > 1]
    open_titles.sort(key=lambda cr: (-gymnasts(cr[1]), cr[0]))
    out = []
    for no, (cluster, rs) in enumerate(open_titles, 1):
        groups: dict[str, list[dict]] = defaultdict(list)
        for r in rs:
            groups[r["work_key"]].append(r)
        order = sorted(groups, key=lambda k: (k.endswith("~ no credit"), -gymnasts(groups[k]), -len(groups[k]), k))
        title = max((r["title"] for r in rs), key=lambda t: sum(r["title"] == t for r in rs))
        for letter, key in zip(ascii_uppercase, order):
            ev = evidence_of(key, groups[key], links)
            for r in sorted(groups[key], key=lambda r: (str(routines[r["routine_id"]]["year"]), r["routine_id"])):
                rt = routines[r["routine_id"]]
                out.append({"row_id": len(out) + 1, "title_no": no, "title": title, "title_gymnasts": gymnasts(rs), "group": letter, "evidence": ev,
                            "gymnast": rt["gymnast_page"], "year": rt["year"], "apparatus": rt["apparatus"],
                            "source_text": cells.get((r["routine_id"], r["track_no"]), ""), "decision": letter,
                            "owner_note": "", "work_key": key, "routine_id": r["routine_id"], "track_no": r["track_no"]})
    return out


def import_decisions(sheet: list[dict], review: list[dict], track_works: list[dict], source: str) -> list[dict]:
    """Owner's sheet (row_id, group, decision, owner_note) -> one decision per split group."""
    split = {(t["routine_id"], t["track_no"]): t for t in track_works}
    local = {r["row_id"]: r for r in review}
    key_of = lambda row_id: split[(local[row_id]["routine_id"], local[row_id]["track_no"])]  # noqa: E731
    target: dict[tuple, str] = {}  # (title_no, letter) -> a split_key of that group
    for r in review:
        target.setdefault((r["title_no"], r["group"]), key_of(r["row_id"])["split_key"])
    out: dict[str, dict] = {}
    for r in sheet:
        t, decision, note = key_of(r["row_id"]), r["decision"].strip().upper(), r["owner_note"].strip()
        changed = decision and decision != local[r["row_id"]]["group"]
        if not (changed or note):
            continue
        row = out.setdefault(t["split_key"], {"title_cluster": t["title_cluster"], "split_key": t["split_key"],
                                              "join_to": "", "owner_note": "", "source": source})
        if changed:
            row["join_to"] = target[(local[r["row_id"]]["title_no"], decision)]
        if note and note not in row["owner_note"]:
            row["owner_note"] = "; ".join(filter(None, [row["owner_note"], note]))
    return sorted(out.values(), key=lambda r: (r["title_cluster"], r["split_key"]))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dir", type=Path, default=INTERIM)
    ap.add_argument("--force", action="store_true", help="rebuild even if the sheet exists (owner's edits are lost)")
    ap.add_argument("--import", dest="sheet", type=Path, help="the owner's sheet exported as CSV")
    args = ap.parse_args(argv)
    target = args.dir / "work_split_review.csv"
    read = lambda name: list(csv.DictReader((args.dir / name).open(encoding="utf-8-sig")))  # noqa: E731
    if args.sheet:
        sheet = list(csv.DictReader(args.sheet.open(encoding="utf-8-sig")))
        rows = import_decisions(sheet, read("work_split_review.csv"), read("track_works.csv"), f"owner sheet {args.sheet.name}")
        with DECISIONS.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=DECISION_FIELDS)
            w.writeheader()
            w.writerows(rows)
        print(f"{sum(bool(r['join_to']) for r in rows)} joins, {sum(bool(r['owner_note']) for r in rows)} notes -> {DECISIONS}")
        return 0
    if target.exists() and not args.force:
        print(f"{target} exists (the owner may have typed into it); use --force to rebuild")
        return 1

    routines = {r["routine_id"]: r for r in read("routines_parsed.csv")}
    cells = {(t["routine_id"], t["track_no"]): t["raw_text"] for t in read("tracks.csv")}
    links = {r["work_key"]: r for r in read("work_mb_links.csv")}
    rows = build_review(read("track_works.csv"), routines, cells, links)
    with target.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"{len({r['title_no'] for r in rows})} titles, {len(rows)} tracks -> {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
