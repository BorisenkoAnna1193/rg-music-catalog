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
  * The owner can say that two rows with different wording are one routine (data/manual/same_routine.csv:
    gymnast_page, year, apparatus, competition_music, routine_music): merged as above, note same_routine_by_owner.
  * The owner can exclude a routine that the source states wrongly (data/manual/routine_exclusions.csv: gymnast_page,
    year, apparatus, music as in the raw table, reason). The raw files keep it; merge_report lists it.
  * Competition rows without music, or without a single apparatus (all-around), only describe
    participation and are skipped.
  * Home-language Wikipedia (native_routines_raw.csv, step 19) comes last and only fills gaps: the English article
    stays the main source. A row whose gymnast, apparatus and year have no English routine is added (source
    native_wiki_<lang>, the English wording from data/manual/native_music_en.csv, note translated_from_<lang>); a row
    with the same music as an English routine is only counted; a row with other music than every English routine of
    that apparatus and year is added and flagged differs_from_english_article (only for languages in COMPARE_LANGS).
    The owner's decisions on those conflicts (data/manual/native_conflict_decisions.csv, keyed by the native routine_id):
    both = keep both rows (note kept_both_by_owner instead of the flag); english = the native row is not added;
    spanish = the native row is added and the English routines named in english_routine_ids are dropped. A cell without an English wording is
    not merged and is listed in native_music_todo.csv. Group routines, rows without music and rows without a readable
    year are skipped (counted in merge_report.json).

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
from rg_music.native_extract import split_year, translate_apparatus
from rg_music.tables import PLACEHOLDERS
from rg_music.years import expand_years, parse_years

INTERIM = Path("data/interim")
SAME_ROUTINE = Path("data/manual/same_routine.csv")
EXCLUSIONS = Path("data/manual/routine_exclusions.csv")
NATIVE_MUSIC = Path("data/manual/native_music_en.csv")
NATIVE_DECISIONS = Path("data/manual/native_conflict_decisions.csv")
NATIVE_UNKNOWN = PLACEHOLDERS | {"desconocida", "desconocido", "неизвестно"}
# Languages whose rows are also compared with the English routines of the same apparatus and year. The Russian articles
# mirror the English ones (342 rows with the same music; the other rows checked are the same music written in Cyrillic),
# so Russian rows only fill gaps until a translation of those cells is worth it.
COMPARE_LANGS = {"es"}
TODO_FIELDS = ["lang", "music_native", "reason", "gymnast_page", "year", "apparatus", "english_music", "source_url"]
MERGED_FIELDS = ["routine_id", "gymnast_page", "table_index", "row_index", "year", "year_source", "apparatus",
                 "music", "source", "notes", "source_url", "revid"]
EVENT_FIELDS = ["routine_id", "competition", "location", "event_year", "source_row"]


def _track_names(cell: str) -> list[str]:
    """Track titles and work names the parser finds in a music cell."""
    return [n for t in parse_music(cell)[1] for n in (t.title, t.work) if n]


def music_score(a: str, b: str) -> float:
    """Similarity of two music cells: the whole text, or the best pair of track titles.

    Comparing titles as well keeps "Avrora by X" and "music from Avrora by X", or one track of a
    three-track cell, from looking like different music. A title that sits whole inside the
    other ("Nur kein genieren" / "Nur kein genieren from Elisabeth") counts as the same.
    """
    best = similarity(a, b)
    titles_b = _track_names(b)
    for x in _track_names(a):
        for y in titles_b:
            nx, ny = norm_music(x), norm_music(y)
            contained = min(len(nx), len(ny)) >= 4 and (f" {nx} " in f" {ny} " or f" {ny} " in f" {nx} ")
            best = max(best, similarity(x, y), 0.9 if contained else 0.0)
    return best


def load_same_routine(path: Path = SAME_ROUTINE) -> set[tuple]:
    """Owner's list: (gymnast_page, year, apparatus, competition music, routine music) that are one routine."""
    if not path.exists():
        return set()
    return {(r["gymnast_page"], int(r["year"]), normalize_apparatus(r["apparatus"]).apparatus,
             r["competition_music"].strip(), r["routine_music"].strip())
            for r in csv.DictReader(path.open(encoding="utf-8-sig"))}


def load_exclusions(path: Path = EXCLUSIONS) -> set[tuple]:
    """Owner's list of routines the source states wrongly: (gymnast_page, year, apparatus, music) as in the raw table."""
    if not path.exists():
        return set()
    return {(r["gymnast_page"], r["year"].strip(), r["apparatus"].strip(), r["music"].strip())
            for r in csv.DictReader(path.open(encoding="utf-8-sig"))}


def _exclusion_key(row: dict) -> tuple:
    return row["gymnast_page"], row["year"].strip(), row["apparatus"].strip(), row["music"].strip()


def _sort_key(m: dict) -> tuple:
    """Output order: gymnast, year (an unreadable year first), apparatus, id."""
    return m["gymnast_page"], m["year"] if isinstance(m["year"], int) else 0, m["apparatus"], m["routine_id"]


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


def merge_sources(routines: list[dict], competitions: list[dict], same_routine: set[tuple] = frozenset(),
                  exclusions: set[tuple] = frozenset()) -> tuple[list[dict], list[dict], dict]:
    excluded = [r for r in routines if _exclusion_key(r) in exclusions]
    routines = [r for r in routines if r not in excluded]
    merged = expand_routines(routines)
    events: list[dict] = []
    seen_events: set[tuple] = set()
    stats = Counter(seasons_expanded=len(merged) - len(routines))
    stats["excluded_by_owner"] = [_base_id(r) for r in excluded]
    used_same: set[tuple] = set()

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
        owner_key = lambda t: (c["gymnast_page"], year, app, c["music"].strip(), t[2]["music"].strip())  # noqa: E731
        owner = next((t for t in near if owner_key(t) in same_routine), None)
        if owner:
            used_same.add(owner_key(owner))
        if owner or (best and best[0] >= FUZZY_OK):
            m = (owner or best)[2]
            m["source"] = "both" if m["source"] == "routine_table" else m["source"]
            extra = (["event_year_differs"] if m["year"] != year else []) + (["same_routine_by_owner"] if owner else [])
            if extra:
                m["notes"] = ";".join(filter(None, [m["notes"], *extra]))
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

    merged.sort(key=_sort_key)
    stats["unused_owner_rows"] = (
        [f"routine_exclusions: {' | '.join(k)}" for k in sorted(exclusions - {_exclusion_key(r) for r in excluded})]
        + [f"same_routine: {' | '.join(map(str, k))}" for k in sorted(set(same_routine) - used_same)])
    return merged, events, dict(stats)


def _clean(cell: str) -> str:
    """Native cells end in zero-width spaces now and then (after a footnote): not part of the text."""
    return cell.replace("\u200b", "").strip()


def load_native_music(path: Path = NATIVE_MUSIC) -> dict[tuple[str, str], str]:
    """English wording of home-language music cells: (lang, music as in the native table) -> music_en."""
    if not path.exists():
        return {}
    return {(r["lang"], _clean(r["music_native"])): r["music_en"].strip()
            for r in csv.DictReader(path.open(encoding="utf-8-sig")) if r["music_en"].strip()}


def _same_music(native: str, english: str, music_en: str) -> bool:
    """The English wording when there is one; without it, an English title found whole in the native text."""
    if music_en:
        return music_score(music_en, english) >= FUZZY_OK
    text = f" {norm_music(native)} "
    titles = [norm_music(n) for n in _track_names(english)]
    return any(len(t) >= 4 and f" {t} " in text for t in titles)


def load_native_decisions(path: Path = NATIVE_DECISIONS) -> dict[str, dict]:
    """Owner's decisions on native rows that differ from the English article: native routine_id -> row."""
    if not path.exists():
        return {}
    return {r["routine_id"]: r for r in csv.DictReader(path.open(encoding="utf-8-sig"))}


def merge_native(merged: list[dict], native: list[dict], translations: dict[tuple[str, str], str],
                 decisions: dict[str, dict] | None = None) -> tuple[list[dict], list[dict], dict]:
    """Home-language rows that fill gaps of the English routines -> (new routines, cells to translate, stats).
    English routines the owner rejected in favour of a native row are listed in stats["dropped_english"]."""
    decisions = decisions or {}
    dropped: list[str] = []
    used: set[str] = set()
    stats: Counter = Counter()
    english: dict[tuple, list[dict]] = {}
    for m in merged:
        if m["music"] and isinstance(m["year"], int):
            key = (m["gymnast_page"], m["year"], normalize_apparatus(m["apparatus"]).apparatus)
            english.setdefault(key, []).append(m)
    added, todo = [], []
    for r in native:
        lang, music = r["lang"], _clean(r["music"])
        year, app = split_year(r["year"]), translate_apparatus(r["apparatus"], lang)
        years = expand_years(year.text)
        if app.kind == "group" or year.category == "group":
            stats["native_group_rows_skipped"] += 1
            continue
        if not music or music.rstrip(".").lower() in NATIVE_UNKNOWN:
            stats["native_rows_without_music"] += 1
            continue
        if app.kind != "individual" or not years:
            stats["native_rows_unreadable"] += 1
            continue
        music_en = translations.get((lang, music), "")
        base = f"{r['gymnast_page']}|{lang}{r['table_index']}|{r['row_index']}"
        apparatus = normalize_apparatus(app.text).apparatus
        for y in years:
            pool = english.get((r["gymnast_page"], y, apparatus), [])
            if any(_same_music(music, m["music"], music_en) for m in pool):
                stats["native_rows_same_as_english"] += 1
                continue
            if pool and lang not in COMPARE_LANGS:
                stats["native_rows_not_compared"] += 1
                continue
            if not music_en:
                todo.append({"lang": lang, "music_native": music, "reason": "differs" if pool else "new",
                             "gymnast_page": r["gymnast_page"], "year": y, "apparatus": app.text,
                             "english_music": " || ".join(m["music"] for m in pool), "source_url": r["source_url"]})
                stats["native_rows_untranslated"] += 1
                continue
            seasonal = len(years) > 1
            routine_id = f"{base}#{y}" if seasonal else base
            decision = decisions.get(routine_id, {}).get("decision", "") if pool else ""
            if decision:
                used.add(routine_id)
            if decision == "english":
                stats["native_rows_rejected_by_owner"] += 1
                continue
            conflict = {"both": "kept_both_by_owner", "spanish": "chosen_by_owner_over_english"}.get(
                decision, "differs_from_english_article" if pool else "")
            if decision == "spanish":
                dropped += [i for i in decisions[routine_id]["english_routine_ids"].split("; ") if i]
            notes = [f"translated_from_{lang}"] + ([f"category_{year.category.replace(' ', '_')}"] if year.category else []) \
                + (["expanded_from_season"] if seasonal else []) + ([conflict] if conflict else [])
            added.append({
                "routine_id": routine_id, "gymnast_page": r["gymnast_page"],
                "table_index": f"{lang}{r['table_index']}", "row_index": r["row_index"], "year": y,
                "year_source": year.text if seasonal else "", "apparatus": app.text, "music": music_en,
                "source": f"native_wiki_{lang}", "notes": ";".join(notes), "source_url": r["source_url"],
                "revid": r["revid"],
            })
            stats[f"native_rows_{decision}_by_owner" if decision else
                  "native_rows_added_with_conflict" if pool else "native_rows_added"] += 1
    stats["dropped_english"] = dropped
    stats["unused_owner_rows"] = [f"native_conflict_decisions: {k}" for k in sorted(set(decisions) - used)]
    return added, todo, dict(stats)


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
    merged, events, stats = merge_sources(routines, competitions, load_same_routine(), load_exclusions())
    native_path = args.dir / "native_routines_raw.csv"
    if native_path.exists():
        added, todo, native_stats = merge_native(merged, read("native_routines_raw.csv"), load_native_music(),
                                                 load_native_decisions())
        dropped = set(native_stats["dropped_english"])
        merged = sorted([m for m in merged if m["routine_id"] not in dropped] + added, key=_sort_key)
        native_stats["unused_owner_rows"] = stats["unused_owner_rows"] + native_stats["unused_owner_rows"]
        stats.update(native_stats)
        _write_csv(args.dir / "native_music_todo.csv", TODO_FIELDS, todo)

    _write_csv(args.dir / "routines_merged.csv", MERGED_FIELDS, merged)
    _write_csv(args.dir / "routine_events.csv", EVENT_FIELDS, events)
    stats.update(routines_in=len(routines), competition_rows_in=len(competitions), routines_out=len(merged),
                 events=len(events), by_source=dict(Counter(m["source"] for m in merged)))
    (args.dir / "merge_report.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
