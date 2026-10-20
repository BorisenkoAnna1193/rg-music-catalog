"""Step 22: update from Wikipedia without silent changes.

Usage:
    python -m rg_music.update                        # which articles changed; compare them with the accepted data
    python -m rg_music.update --import <sheet.csv>   # owner's decisions from the update_review sheet

1. The latest revision of every article (50 per request) is compared with the revision our data came from.
2. Changed articles are downloaded into data/raw/_update/ (the main cache stays as it is, so a rebuild from the cache
   gives the same result) and their tables are read by the code of steps 1 and 19.
3. Rows are compared by CONTENT (year, apparatus, music, competition), not by position: a row inserted at the top of a
   table does not make the others look changed.
4. Music where there was none (a new row, or a row that was empty / "??" / "Unknown"), in any year = new music:
   accepted at once by rule and listed (owner, 2026-10-20). Music that was known and is now different or gone is a
   warning for the owner: data/interim/update_review.csv, nothing changes until she accepts it.

The accepted and rejected changes are kept in data/manual/wiki_updates.csv (one row per change, the rows as JSON) and
applied by merge.py on top of the raw files with `apply_updates`; a rejected change is not shown again.
After an update: `python -m rg_music.pipeline --from merge`, then `python -m rg_music.work_review --new` for new music.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from .tables import PLACEHOLDERS
from .years import expand_years

INTERIM = Path("data/interim")
UPDATES = Path("data/manual/wiki_updates.csv")
STAGE_CACHE = Path("data/raw/_update")

# kind -> raw file
RAW = {"routine": "routines_raw.csv", "competition": "competitions_raw.csv", "native": "native_routines_raw.csv"}
CONTENT = ["year", "apparatus", "music", "competition", "location"]

UPDATE_FIELDS = ["change_key", "kind", "change", "decision", "decided_by", "decided_on", "reviewed", "gymnast_page",
                 "lang", "year", "apparatus", "old_music", "new_music", "owner_note", "old_row", "new_row"]
REVIEW_FIELDS = ["change_key", "kind", "change", "gymnast_page", "lang", "year", "apparatus", "competition",
                 "old_music", "new_music", "source_url", "decision", "owner_note"]
# what a source writes when the music is not known yet (any number of "?" counts too)
NO_MUSIC = PLACEHOLDERS | {"unknown", "desconocida", "desconocido", "неизвестно", "tbd", "to be announced"}
DECISIONS = {"accept": "accept", "reject": "reject", "принять": "accept", "отклонить": "reject"}


def _norm(text: str) -> str:
    return " ".join((text or "").split())


def has_music(row: dict | None) -> bool:
    text = _norm((row or {}).get("music", "")).strip(' "\'.').lower()
    return bool(text) and text not in NO_MUSIC and not re.fullmatch(r"[?\s]+", text)


def content_key(row: dict) -> tuple:
    """What a row says, without its position in the table or the revision it came from."""
    return (row["gymnast_page"], row.get("lang", "")) + tuple(_norm(row.get(f, "")) for f in CONTENT)


def change_key(kind: str, old: dict | None, new: dict | None) -> str:
    text = json.dumps([kind, old and content_key(old), new and content_key(new)], ensure_ascii=False)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------------------------------------- decisions layer
def load_updates(path: Path | None = None) -> list[dict]:
    path = path or UPDATES
    return list(csv.DictReader(path.open(encoding="utf-8-sig"))) if path.exists() else []


def apply_updates(rows: list[dict], kind: str, updates: list[dict]) -> tuple[list[dict], list[str]]:
    """Raw rows of one kind + the accepted changes -> (rows, change keys whose old row was not found)."""
    out = list(rows)
    missing = []
    for u in updates:
        if u["kind"] != kind or u["decision"] != "accept":
            continue
        if u["old_row"]:
            key = content_key(json.loads(u["old_row"]))
            i = next((i for i, r in enumerate(out) if content_key(r) == key), None)
            if i is None:
                missing.append(u["change_key"])
                continue
            out.pop(i)
        if u["new_row"]:
            out.append(json.loads(u["new_row"]))
    return out, missing


def write_updates(updates: list[dict], path: Path | None = None) -> None:
    with (path or UPDATES).open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=UPDATE_FIELDS)
        w.writeheader()
        w.writerows(sorted(updates, key=lambda u: (u["gymnast_page"], u["year"], u["kind"], u["change_key"])))


# ------------------------------------------------------------------------------------------------------ diff
def _years(row: dict) -> list[int]:
    return expand_years(row.get("year", ""))


def _unmatched(rows: list[dict], other: list[dict]) -> list[dict]:
    """Rows with no row of the same content in `other` (duplicates are matched one to one)."""
    left = Counter(content_key(r) for r in other)
    out = []
    for r in rows:
        if left[content_key(r)]:
            left[content_key(r)] -= 1
        else:
            out.append(r)
    return out


def diff_page(kind: str, old: list[dict], new: list[dict]) -> list[dict]:
    """Differences between the accepted rows of one article and its rows now, each {change, old, new}:
    new_music (music where there was none: a new row or a filled placeholder), changed (known music replaced),
    removed (known music gone). Differences without music on either side are left out."""
    removed, added = _unmatched(old, new), _unmatched(new, old)
    changes = []
    for r in removed:  # the same apparatus in an overlapping year = the row was edited
        pair = next((a for a in added if _norm(a["apparatus"]).lower() == _norm(r["apparatus"]).lower()
                     and _norm(a.get("competition", "")) == _norm(r.get("competition", ""))
                     and set(_years(a)) & set(_years(r))), None)
        if pair:
            added.remove(pair)
        before, after = has_music(r), has_music(pair)
        if before or after:
            changes.append({"change": "new_music" if not before else "changed" if after else "removed",
                            "old": r, "new": pair})
    changes += [{"change": "new_music", "old": None, "new": a} for a in added if has_music(a)]
    return changes


def _fresh_id(row: dict) -> dict:
    """A new row keeps its own id apart from the old ones: the table is prefixed with u<revid>."""
    return {**row, "table_index": f"u{row['revid']}t{row['table_index']}"}


# ------------------------------------------------------------------------------------------------------ fetch
def tracked_pages() -> list[dict]:
    """Every article our data came from: {lang, title, requested_title, gymnast_page, revid, kinds}."""
    pages = []
    report = INTERIM / "extract_report.json"
    for e in json.loads(report.read_text(encoding="utf-8")) if report.exists() else []:
        if e.get("page"):
            pages.append({"lang": "en", "title": e["page"], "requested_title": e["requested_title"],
                          "gymnast_page": e["page"], "revid": e["revid"]})
    native = INTERIM / RAW["native"]
    seen = set()
    for r in csv.DictReader(native.open(encoding="utf-8")) if native.exists() else []:
        if (r["lang"], r["native_title"]) not in seen:
            seen.add((r["lang"], r["native_title"]))
            pages.append({"lang": r["lang"], "title": r["native_title"], "requested_title": r["native_title"],
                          "gymnast_page": r["gymnast_page"], "revid": int(r["revid"])})
    return pages


def fetch_rows(page: dict, client) -> dict[str, list[dict]]:
    """Rows of one article as it is now, by kind (the page is cached in data/raw/_update/)."""
    from .extract import page_rows
    from .native_extract import native_rows

    wiki = client.get_page(page["title"])
    if wiki.revid != page["current_revid"]:
        wiki = client.get_page(page["title"], refresh=True)
    if page["lang"] == "en":
        routines, competitions, _ = page_rows(wiki, page["requested_title"])
        return {"routine": routines, "competition": competitions}
    return {"native": [{"gymnast_page": page["gymnast_page"], "lang": page["lang"], "native_title": wiki.title,
                        "revid": wiki.revid, **r, "source_url": wiki.url} for r in native_rows(wiki.html, page["lang"])]}


def run_update(client_for, today: str) -> dict:
    """Check every tracked article; write update_review.csv, update_staged.json and the new-music rows."""
    updates = load_updates()
    decided = {u["change_key"]: u for u in updates}
    accepted = {}
    for kind, name in RAW.items():
        path = INTERIM / name
        raw = list(csv.DictReader(path.open(encoding="utf-8"))) if path.exists() else []
        accepted[kind] = apply_updates(raw, kind, updates)[0]
    by_page = defaultdict(list)
    for kind, rows in accepted.items():
        for r in rows:
            by_page[(r.get("lang") or "en", r.get("native_title") or r["gymnast_page"], kind)].append(r)

    pages = tracked_pages()
    for lang in {p["lang"] for p in pages}:
        current = client_for(lang).revids([p["title"] for p in pages if p["lang"] == lang])
        for p in pages:
            if p["lang"] == lang:
                p["current_revid"] = current.get(p["title"])
    # the raw files keep the revision of the first download, so an article edited once is compared on every run:
    # the comparison is by content, and decided changes are skipped
    changed = [p for p in pages if p["current_revid"] and p["current_revid"] != p["revid"]]
    missing = [p["title"] for p in pages if not p["current_revid"]]

    review, staged, new_rows, report = [], {}, [], Counter()
    for p in changed:
        try:
            fresh = fetch_rows(p, client_for(p["lang"]))
        except Exception as exc:  # keep going, list the failure
            logging.error("failed: %s: %s", p["title"], exc)
            report["fetch_failed"] += 1
            continue
        for kind, rows in fresh.items():
            old = by_page.get((p["lang"], p["title"] if p["lang"] != "en" else p["gymnast_page"], kind), [])
            for c in diff_page(kind, old, rows):
                key = change_key(kind, c["old"], c["new"])
                if key in decided:
                    report[f"already_{decided[key]['decision']}"] += 1
                    continue
                new = c["new"] and _fresh_id(c["new"])
                row = c["new"] or c["old"]
                entry = {"change_key": key, "kind": kind, "change": c["change"], "gymnast_page": row["gymnast_page"],
                         "lang": row.get("lang", "en"), "year": row["year"], "apparatus": row["apparatus"],
                         "competition": row.get("competition", ""), "old_music": c["old"]["music"] if c["old"] else "",
                         "new_music": c["new"]["music"] if c["new"] else "", "source_url": row["source_url"]}
                staged[key] = {"kind": kind, "change": c["change"], "old_row": c["old"], "new_row": new}
                report[c["change"]] += 1
                if c["change"] == "new_music":
                    review.append({**entry, "decision": "accept", "owner_note": "added by rule (new music)"})
                    new_rows.append(_update_row(entry, staged[key], "accept", "rule", today, ""))
                else:
                    review.append({**entry, "decision": "", "owner_note": ""})

    write_updates(updates + new_rows)
    for u in updates:  # rows added by rule on an earlier run stay on the sheet until the owner has seen them
        if u["decided_by"] == "rule" and not u.get("reviewed"):
            new = json.loads(u["new_row"]) if u["new_row"] else {}
            review.append({**{f: u.get(f, "") for f in REVIEW_FIELDS}, "competition": new.get("competition", ""),
                           "source_url": new.get("source_url", ""), "decision": "accept",
                           "owner_note": "added by rule (new music)"})
    review.sort(key=lambda r: (r["change"] == "new_music", r["gymnast_page"], r["year"]))
    with (INTERIM / "update_review.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=REVIEW_FIELDS)
        w.writeheader()
        w.writerows(review)
    (INTERIM / "update_staged.json").write_text(json.dumps(staged, ensure_ascii=False, indent=1), encoding="utf-8")
    summary = {"date": today, "pages_checked": len(pages), "pages_changed": len(changed), "pages_missing": missing,
               **report, "to_review": sum(1 for r in review if not r["decision"])}
    (INTERIM / "update_report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def _update_row(entry: dict, staged: dict, decision: str, by: str, today: str, note: str) -> dict:
    return {"change_key": entry["change_key"], "kind": staged["kind"], "change": staged["change"],
            "decision": decision, "decided_by": by, "decided_on": today, "reviewed": "yes" if by == "owner" else "",
            "gymnast_page": entry["gymnast_page"],
            "lang": entry["lang"], "year": entry["year"], "apparatus": entry["apparatus"],
            "old_music": entry["old_music"], "new_music": entry["new_music"], "owner_note": note,
            "old_row": json.dumps(staged["old_row"], ensure_ascii=False) if staged["old_row"] else "",
            "new_row": json.dumps(staged["new_row"], ensure_ascii=False) if staged["new_row"] else ""}


def import_decisions(sheet: Path, today: str) -> Counter:
    """Owner's decisions (accept / reject, or принять / отклонить) -> data/manual/wiki_updates.csv.
    A row is refused if its music differs from what was staged (the sheet must be the one this run produced)."""
    staged = json.loads((INTERIM / "update_staged.json").read_text(encoding="utf-8"))
    updates = {u["change_key"]: u for u in load_updates()}
    stats = Counter()
    for r in csv.DictReader(sheet.open(encoding="utf-8-sig")):
        decision = DECISIONS.get(r["decision"].strip().lower())
        if not decision:
            stats["undecided"] += 1
            continue
        s = staged.get(r["change_key"])
        if s is None and r["change_key"] in updates:  # a row added by rule on an earlier run
            u = updates[r["change_key"]]
            s = {"kind": u["kind"], "change": u["change"], "old_row": json.loads(u["old_row"]) if u["old_row"] else None,
                 "new_row": json.loads(u["new_row"]) if u["new_row"] else None}
        if s is None:
            raise SystemExit(f"unknown change_key {r['change_key']}: import the sheet of the last update run")
        if (s["old_row"] or {}).get("music", "") != r["old_music"] or (s["new_row"] or {}).get("music", "") != r["new_music"]:
            raise SystemExit(f"row {r['change_key']} differs from update_staged.json: not imported")
        by = "rule" if s["change"] == "new_music" and decision == "accept" else "owner"
        updates[r["change_key"]] = {**_update_row(r | {"lang": r.get("lang", "en")}, s, decision, by, today,
                                                  r.get("owner_note", "").strip()), "reviewed": "yes"}
        stats[decision] += 1
    write_updates(list(updates.values()))
    return stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--import", dest="sheet", type=Path, help="owner's update_review sheet exported as CSV")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    today = date.today().isoformat()
    if args.sheet:
        print(json.dumps(import_decisions(args.sheet, today), ensure_ascii=False))
        return 0

    from .wiki_client import WikiClient
    clients: dict = {}
    summary = run_update(lambda lang: clients.setdefault(lang, WikiClient(cache_dir=STAGE_CACHE, lang=lang)), today)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    if summary["to_review"]:
        print(f"{summary['to_review']} changes of old years wait for the owner: data/interim/update_review.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
