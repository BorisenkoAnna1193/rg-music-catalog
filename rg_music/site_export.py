"""Export the catalogue for the static site: one compact JSON file the browser loads (site/data.json).

Only what the dashboard shows: every World Championship gymnast (most have no known music yet), the routines, the works, versions and excerpts of that
music. Records refer to each other by position in their list (a "foreign key" is an index), which keeps the file
small; the site computes every statistic (rankings by gymnasts and by routines, filters) from these lists.

    apparatus  [name, name_ru]
    countries  {country_id: [name, name_ru]}
    gymnasts   [name, name_ru, country_id, wikipedia_url or "", [World Championship years]] - every gymnast, music or not
    works      [name, name_ru, author, author_ru, author_type, kind, from_title, from_type, original_performer]
               kind = classical / folk / film / song / other
    versions   [work, performer, version_type]
    excerpts   [work, name]
    routines   [gymnast, year, apparatus, variant, context, [[version, excerpt or -1, title], ...], [event, ...]]

Also writes site/index.html: site/app.html (the page itself, a fragment as claude.ai artifacts expect) wrapped into a
full HTML document for GitHub Pages, with the data inline so the file also opens straight from disk.

Usage:
    python -m rg_music.site_export [--db data/catalog.sqlite] [--out site/data.json]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

DB = Path("data/catalog.sqlite")
OUT = Path("site/data.json")


def kind(author_type: str | None, is_classical: int | None, from_title: str | None) -> str:
    if is_classical:
        return "classical"
    if author_type == "folk":
        return "folk"
    if from_title:
        return "film"
    if author_type == "performer":
        return "song"
    return "other"


def export(con: sqlite3.Connection) -> dict:
    q = lambda sql: con.execute(sql).fetchall()  # noqa: E731
    apparatus = q("SELECT apparatus_id, name, name_ru FROM apparatus ORDER BY apparatus_id")
    app_ix = {a[0]: i for i, a in enumerate(apparatus)}

    with_music = q("""SELECT DISTINCT r.routine_id FROM routine r JOIN track t USING (routine_id) WHERE t.version_id IS NOT NULL""")
    keep = {r[0] for r in with_music}
    routines = [r for r in q("""SELECT routine_id, gymnast_id, year, apparatus_id, variant, context FROM routine
                                ORDER BY gymnast_id, year, apparatus_id, routine_id""") if r[0] in keep]

    gymnasts = q("""SELECT gymnast_id, canonical_name, name_ru, country_id, wiki_page, wc_years FROM gymnast
                    ORDER BY canonical_name""")
    gym_ix = {g[0]: i for i, g in enumerate(gymnasts)}

    tracks = defaultdict(list)
    for routine_id, version_id, excerpt_id, title in q("""SELECT routine_id, version_id, excerpt_id, title FROM track
                                                          WHERE version_id IS NOT NULL ORDER BY routine_id, track_no"""):
        tracks[routine_id].append((version_id, excerpt_id, title))
    used_versions = {v for ts in tracks.values() for v, _, _ in ts}
    versions = [v for v in q("SELECT version_id, work_id, performer, version_type FROM version ORDER BY version_id") if v[0] in used_versions]
    used_works = {v[1] for v in versions}
    works = [w for w in q("""SELECT work_id, name, name_ru, author, author_ru, author_type, is_classical, from_title, from_type,
                                    original_performer FROM work ORDER BY work_id""") if w[0] in used_works]
    work_ix = {w[0]: i for i, w in enumerate(works)}
    ver_ix = {v[0]: i for i, v in enumerate(versions)}
    excerpts = [e for e in q("SELECT excerpt_id, work_id, name FROM excerpt ORDER BY excerpt_id") if e[1] in work_ix]
    exc_ix = {e[0]: i for i, e in enumerate(excerpts)}
    events = defaultdict(list)
    for routine_id, competition, year in q("SELECT routine_id, competition, event_year FROM routine_event ORDER BY event_year"):
        events[routine_id].append(competition)

    countries = {c[0]: [c[1], c[2] or ""] for c in q("SELECT country_id, name, name_ru FROM country")
                 if c[0] in {g[3] for g in gymnasts}}
    return {
        "built": date.today().isoformat(),
        "apparatus": [[a[1], a[2] or ""] for a in apparatus],
        "countries": countries,
        "gymnasts": [[g[1], g[2] or "", g[3] or "", "https://en.wikipedia.org/wiki/" + g[4].replace(" ", "_") if g[4] else "",
                      [int(y) for y in (g[5] or "").split(",") if y.strip().isdigit()]] for g in gymnasts],
        "works": [[w[1], w[2] or "", w[3] or "", w[4] or "", w[5] or "", kind(w[5], w[6], w[7]), w[7] or "", w[8] or "", w[9] or ""]
                  for w in works],
        "versions": [[work_ix[v[1]], v[2] or "", v[3] or ""] for v in versions],
        "excerpts": [[work_ix[e[1]], e[2]] for e in excerpts],
        "routines": [[gym_ix[r[1]], r[2], app_ix.get(r[3], -1), r[4] or "", r[5] or "",
                      [[ver_ix[v], exc_ix.get(e, -1), t or ""] for v, e, t in tracks[r[0]]], events.get(r[0], [])]
                     for r in routines],
    }


def page(fragment: str, data_json: str) -> str:
    """site/app.html is a page fragment (head parts, then the body); wrap it into a full document for GitHub Pages,
    with the data inline (window.RG_DATA), so index.html also works when opened straight from disk."""
    head, _, body = fragment.partition('<div class="wrap">')
    inline = data_json.replace("</", "<\\/")
    return ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
            f'{head.strip()}\n<script>window.RG_DATA = {inline};</script>\n</head>\n<body>\n<div class="wrap">{body}</body>\n</html>\n')


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", type=Path, default=DB)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)
    data = export(sqlite3.connect(args.db))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    args.out.write_text(text, encoding="utf-8")
    app = args.out.parent / "app.html"
    if app.exists():  # the GitHub Pages entry point, built from the same fragment the claude.ai page uses
        (args.out.parent / "index.html").write_text(page(app.read_text(encoding="utf-8"), text), encoding="utf-8")
    print(f"{args.out}: {len(data['gymnasts'])} gymnasts, {len(data['routines'])} routines, {len(data['works'])} works, "
          f"{len(data['versions'])} versions, {args.out.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
