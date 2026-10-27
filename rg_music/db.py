"""Build the SQLite catalogue from the reviewed CSV layers (MVP schema, docs/db_schema.md).

Rebuilt from scratch on every run (idempotent): the database is a product of the CSV files, never edited by hand.

Tables:
    country        ISO countries with Russian short names            data/reference/countries.csv
    apparatus      Hoop, Ball, Clubs, Ribbon, Rope, Gala...           data/reference/apparatus.csv
    gymnast        every World Championship gymnast (with or without an article and music) + any page with music
                   data/interim/wc_gymnasts_final.csv, gymnast_names_ru.csv,
                   data/manual/gymnast_country_overrides.csv (owner); AIN (neutral athletes) is never a country: without an
                   override the country stays empty
    routine        one row per routine and year                       data/interim/routines_parsed.csv
    routine_event  competitions where a routine was performed         data/interim/routine_events.csv
    work           music works with author, film, lyrics, classical   data/interim/works.csv + data/manual/*_names_ru.csv
    version        a work as performed by one performer               data/interim/versions.csv
    excerpt        named parts of a work (Adagio of Spartacus...)     data/interim/track_works.csv
    track          one piece of music in a routine -> version        data/interim/tracks.csv + track_works.csv
Russian names are empty when unknown; the site falls back to the English / Latin name.

Usage:
    python -m rg_music.db [--out data/catalog.sqlite]
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from pathlib import Path

INTERIM = Path("data/interim")
REFERENCE = Path("data/reference")
MANUAL = Path("data/manual")
OUT = Path("data/catalog.sqlite")

SCHEMA = """
CREATE TABLE country (country_id TEXT PRIMARY KEY, name TEXT NOT NULL, name_ru TEXT, status TEXT);
CREATE TABLE apparatus (apparatus_id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, name_ru TEXT);
CREATE TABLE gymnast (
    gymnast_id INTEGER PRIMARY KEY, canonical_name TEXT NOT NULL, name_ru TEXT, wiki_page TEXT UNIQUE,
    fig_id TEXT, country_id TEXT REFERENCES country, first_year INTEGER, last_year INTEGER,
    wc_years TEXT, championships INTEGER, events TEXT);
CREATE TABLE routine (
    routine_id TEXT PRIMARY KEY, gymnast_id INTEGER NOT NULL REFERENCES gymnast, year INTEGER, year_source TEXT,
    apparatus_id INTEGER REFERENCES apparatus, variant TEXT, context TEXT, music_raw TEXT, parse_status TEXT,
    source TEXT, source_url TEXT, revid INTEGER);
CREATE TABLE routine_event (
    routine_event_id INTEGER PRIMARY KEY, routine_id TEXT NOT NULL REFERENCES routine, competition TEXT,
    location TEXT, event_year INTEGER);
CREATE TABLE work (
    work_id INTEGER PRIMARY KEY, work_key TEXT UNIQUE NOT NULL, name TEXT NOT NULL, name_ru TEXT,
    author_type TEXT, author TEXT, author_ru TEXT, original_performer TEXT, from_title TEXT, from_type TEXT,
    has_lyrics TEXT, is_classical INTEGER, classical_basis TEXT, author_source TEXT, name_ru_source TEXT);
CREATE TABLE version (
    version_id INTEGER PRIMARY KEY, version_key TEXT UNIQUE NOT NULL, work_id INTEGER NOT NULL REFERENCES work,
    performer TEXT, version_type TEXT);
CREATE TABLE excerpt (excerpt_id INTEGER PRIMARY KEY, work_id INTEGER NOT NULL REFERENCES work, name TEXT NOT NULL,
    UNIQUE (work_id, name));
CREATE TABLE track (
    track_id INTEGER PRIMARY KEY, routine_id TEXT NOT NULL REFERENCES routine, track_no INTEGER, title TEXT,
    artist_text TEXT, performer_text TEXT, version_id INTEGER REFERENCES version, excerpt_id INTEGER REFERENCES excerpt,
    match_method TEXT, status TEXT, raw_text TEXT);
CREATE INDEX routine_gymnast ON routine (gymnast_id);
CREATE INDEX track_routine ON track (routine_id);
CREATE INDEX track_version ON track (version_id);
CREATE INDEX version_work ON version (work_id);
"""


def read(path: Path) -> list[dict]:
    return list(csv.DictReader(path.open(encoding="utf-8-sig")))


def _int(value: str) -> int | None:
    return int(value) if str(value).strip().lstrip("-").isdigit() else None


def build(con: sqlite3.Connection, interim: Path = INTERIM, reference: Path = REFERENCE, manual: Path = MANUAL) -> dict:
    con.executescript(SCHEMA)
    con.executemany("INSERT INTO country VALUES (?, ?, ?, ?)",
                    [(r["country_id"], r["name"], r["name_ru"] or None, r["status"]) for r in read(reference / "countries.csv")])

    routines = read(interim / "routines_parsed.csv")
    apparatus = {r["apparatus"]: r["name_ru"] for r in read(reference / "apparatus.csv")}
    for name in sorted({r["apparatus"] for r in routines if r["apparatus"]} - set(apparatus)):
        apparatus[name] = ""
    con.executemany("INSERT INTO apparatus (name, name_ru) VALUES (?, ?)", [(k, v or None) for k, v in apparatus.items()])
    app_id = {name: i for i, name in con.execute("SELECT apparatus_id, name FROM apparatus")}

    names_ru = {r["wiki_page"]: r["name_ru"] for r in read(interim / "gymnast_names_ru.csv") if r["name_ru"]}
    overrides = {r["wiki_page"]: r["country_id"] for r in read(manual / "gymnast_country_overrides.csv")} \
        if (manual / "gymnast_country_overrides.csv").exists() else {}
    not_countries = {"AIN"}
    gymnasts = read(interim / "wc_gymnasts_final.csv")
    seen = {g["wiki_page"] for g in gymnasts if g["wiki_page"]}
    for page in sorted({r["gymnast_page"] for r in routines} - seen):  # a page with music but no World Championship
        gymnasts.append({"canonical_name": page, "name_ru": "", "wiki_page": page, "fig_id": "", "country_id": "",
                         "first_year": "", "last_year": "", "years": "", "championships": "", "events": ""})
    con.executemany(
        """INSERT INTO gymnast (canonical_name, name_ru, wiki_page, fig_id, country_id, first_year, last_year, wc_years,
           championships, events) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [(g["canonical_name"], names_ru.get(g["wiki_page"]) or g["name_ru"] or None, g["wiki_page"] or None, g["fig_id"] or None,
          overrides.get(g["wiki_page"]) or (g["country_id"] if g["country_id"] not in not_countries else None) or None,
          _int(g["first_year"]), _int(g["last_year"]), g["years"] or None, _int(g["championships"]),
          g.get("events") or None) for g in gymnasts])
    gym_id = {page: i for i, page in con.execute("SELECT gymnast_id, wiki_page FROM gymnast WHERE wiki_page IS NOT NULL")}

    con.executemany("INSERT INTO routine VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [
        (r["routine_id"], gym_id[r["gymnast_page"]], _int(r["year"]), r["year_source"] or None, app_id.get(r["apparatus"]),
         r["variant"] or None, r["context"] or None, r["music_raw"], r["parse_status"], r["source"], r["source_url"], _int(r["revid"]))
        for r in routines])
    known = {r["routine_id"] for r in routines}
    con.executemany("INSERT INTO routine_event (routine_id, competition, location, event_year) VALUES (?, ?, ?, ?)",
                    [(e["routine_id"], e["competition"], e["location"], _int(e["event_year"]))
                     for e in read(interim / "routine_events.csv") if e["routine_id"] in known])

    work_ru = {r["work_key"]: (r["name_ru"], r["source"]) for r in read(manual / "work_names_ru.csv")}
    author_ru = {r["name"]: r["name_ru"] for r in read(manual / "composer_names_ru.csv")}
    rows = []
    for w in read(interim / "works.csv"):
        author = w["author"] or w["composer"] or w["classical_composer"]
        author_type = w["author_type"] or ("composer" if w["is_classical"] == "1" and author else "")
        if author_type == "performer":
            author = ""
        ru, ru_source = work_ru.get(w["work_key"], ("", ""))
        rows.append((w["work_key"], w["work"], ru or None, author_type or None, author or None, author_ru.get(author) or None,
                     w["original_performer"] or None, w["from_title"] or None, w["from_type"] or None, w["has_lyrics"] or None,
                     _int(w["is_classical"]), w["classical_basis"], w["author_source"] or None, ru_source or None))
    con.executemany("""INSERT INTO work (work_key, name, name_ru, author_type, author, author_ru, original_performer, from_title,
                       from_type, has_lyrics, is_classical, classical_basis, author_source, name_ru_source)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", rows)
    work_id = {k: i for i, k in con.execute("SELECT work_id, work_key FROM work")}

    con.executemany("INSERT INTO version (version_key, work_id, performer, version_type) VALUES (?, ?, ?, ?)",
                    [(v["version_key"], work_id[v["work_key"]], v["performer"] or None, v["version_type"])
                     for v in read(interim / "versions.csv")])
    version_id = {k: i for i, k in con.execute("SELECT version_id, version_key FROM version")}

    track_works = {(t["routine_id"], t["track_no"]): t for t in read(interim / "track_works.csv")}
    excerpts = sorted({(work_id[t["work_key"]], t["excerpt"]) for t in track_works.values() if t["excerpt"]})
    con.executemany("INSERT INTO excerpt (work_id, name) VALUES (?, ?)", excerpts)
    excerpt_id = {(w, n): i for i, w, n in con.execute("SELECT excerpt_id, work_id, name FROM excerpt")}

    tracks = []
    for t in read(interim / "tracks.csv"):
        if t["routine_id"] not in known:
            continue
        tw = track_works.get((t["routine_id"], t["track_no"]))
        vid = version_id.get(tw["version_key"]) if tw else None
        eid = excerpt_id.get((work_id[tw["work_key"]], tw["excerpt"])) if tw and tw["excerpt"] else None
        tracks.append((t["routine_id"], _int(t["track_no"]), t["title"] or None, t["artist"] or None, t["performer"] or None,
                       vid, eid, tw["method"] if tw else None, t["status"], t["raw_text"]))
    con.executemany("""INSERT INTO track (routine_id, track_no, title, artist_text, performer_text, version_id, excerpt_id,
                       match_method, status, raw_text) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", tracks)
    con.commit()
    return {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("country", "apparatus", "gymnast", "routine", "routine_event", "work", "version", "excerpt", "track")}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)
    args.out.unlink(missing_ok=True)
    con = sqlite3.connect(args.out)
    con.execute("PRAGMA foreign_keys = ON")
    counts = build(con)
    problems = con.execute("PRAGMA foreign_key_check").fetchall()
    con.close()
    print(f"{args.out}: " + ", ".join(f"{k} {v}" for k, v in counts.items()) + (f"; FK problems {len(problems)}" if problems else ""))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
