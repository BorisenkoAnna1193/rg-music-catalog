"""Collect the individual gymnasts of the senior continental championships (Europe, Asia, Africa, Pan America).

Step 24 (owner, 2026-10-26): the gymnast list is the union of the World Championships and the continental
championships; junior championships and Oceania are not taken. Every championship article linked from the four index
pages is read in two ways:
  - full result tables (individual qualification / all-around), the same tables as the World Championships, read by
    the worlds.py parser, and the apparatus finals (stage "final": most articles have no qualification table, so a
    gymnast who did not compete in the all-around is found only in a final); only 23 articles have them (Europe 2004-2026 every other year and since 2020, Asia 2009, 2011,
    2023-2026, Pan America 2023, 2026);
  - "Medal winners" tables (Event | Gold | Silver | Bronze): the first three of every individual event (all-around and
    the apparatus finals). For most championships this is the only list there is (all of Africa, Europe 1978-2002, most
    of Asia and Pan America), so a gymnast's championship history shows these only where she won a medal.
Group, team and junior events are skipped (a section, a sub-header row or the event name says so); on the general
Pan American Gymnastics Championships articles only the rhythmic section is read.

Usage:
    python -m rg_music.continental [--refresh]
Output (data/interim/):
    cont_appearances.csv   one row per gymnast per table row (raw layer, same columns as wc_appearances.csv)
    cont_report.json       per article: tables used, people per stage, skipped events
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import asdict
from pathlib import Path
from urllib.parse import unquote

from bs4 import BeautifulSoup, Tag

from .countries import CountryReference, load_reference, normalize
from .wiki_client import WikiClient
from .worlds import NAME_HEADERS, NATION_HEADERS, TEAM_LAYOUT, Appearance, _cells, _parse_flat, _parse_team_layout, _person, _stage

INTERIM = Path("data/interim")
# index article -> championship articles it links to (titles as Wikipedia writes them)
INDEXES = {
    "europe": ("Rhythmic Gymnastics European Championships",
               r"\d{4} (?:Rhythmic Gymnastics European|European Rhythmic Gymnastics) Championships"),
    "asia": ("Asian Gymnastics Championships", r"\d{4} Asian Rhythmic Gymnastics Championships"),
    "africa": ("African Rhythmic Gymnastics Championships", r"\d{4} African Rhythmic Gymnastics Championships"),
    "panam": ("Pan American Gymnastics Championships", r"\d{4} Pan American (?:Rhythmic )?Gymnastics Championships"),
}
# a section, sub-header row or event that is not a senior individual rhythmic event
NOT_INDIVIDUAL = re.compile(r"junior|oceania|\bmen\b|artistic|trampoline|acrobatic|aerobic|tumbling|"
                            r"group|team|club\b|nation|countr|\d\s*(?:x|×)|\b[2-5]\s+[a-z]|\+", re.I)
APPARATUS_FINAL = re.compile(r"(?:senior\s+)?(?:hoop|ball|clubs|ribbon|rope|free ?hands?)(?:\s+final)?", re.I)
NO_MEDAL = re.compile(r"^(none|not|no)\b.*awarded|^vacant$|^—$", re.I)
INDIVIDUAL_EVENT = re.compile(r"all[- ]?around|individual|hoop|ball|clubs|ribbon|rope|free ?hands?|freehand", re.I)


def championship_titles(index_html: str, pattern: str) -> list[tuple[int, str]]:
    """(year, title) of every existing article linked from an index page whose title matches the pattern."""
    soup = BeautifulSoup(index_html, "lxml")
    out: dict[str, int] = {}
    for a in soup.select('a[href^="/wiki/"]'):
        title = unquote(a["href"][len("/wiki/"):].split("#")[0]).replace("_", " ")
        if re.fullmatch(pattern, title):
            out.setdefault(title, int(title[:4]))
    return sorted(((y, t) for t, y in out.items()), key=lambda x: (x[0], x[1]))


def section_path(tag: Tag) -> list[str]:
    """Headings the tag sits under, outermost first: ['Results', 'Senior', 'All-around']."""
    path, level = [], 7
    for h in tag.find_all_previous(["h2", "h3", "h4", "h5"]):
        lv = int(h.name[1])
        if lv < level:
            path.append(h.get_text(" ", strip=True))
            level = lv
            if lv == 2:
                break
    return path[::-1]


def _is_country(title: str, ref: CountryReference) -> bool:
    return normalize(title) in ref.alias


def _flag(img: Tag) -> str:
    m = re.search(r"Flag_of_(.+?)\.svg", unquote(img.get("src", "")))
    return m.group(1).replace("_", " ") if m else ""


def medalists(cell: Tag, ref: CountryReference) -> list[tuple[str, str, str]]:
    """(name, article title, nation) of the people in a Gold / Silver / Bronze cell.

    Layouts: 'Name<br>[flag] Country', '[flag] Name (RSA)', and ties: several people in one cell, each with her own
    country ('Name1 [flag] Country1 Name2 [flag] Country2'). A country belongs to the person it follows; a bare flag
    right before a name belongs to that name. A team cell (a country in bold and several names) gives several people;
    the caller skips team events before getting here.
    """
    tokens: list[list] = []  # ['person', name, title] | ['country', text] | ['flag', text]
    for el in cell.find_all(["a", "img", "abbr"]):
        if el.name == "img":
            if flag := _flag(el):
                tokens.append(["flag", flag])
        elif el.name == "abbr":
            tokens.append(["country", el.get_text(strip=True)])
        else:
            title = el.get("title", "").replace(" (page does not exist)", "")
            if not title or el.find("img"):
                continue
            if _is_country(title, ref):
                if tokens and tokens[-1][0] == "flag":
                    tokens.pop()  # the flag of this country link
                tokens.append(["country", title])
            elif not el.find_parent(class_="flagicon"):
                tokens.append(["person", el.get_text(" ", strip=True), title if el["href"].startswith("/wiki/") else ""])
    people = []
    for k, t in enumerate(tokens):
        if t[0] != "person":
            continue
        after = ""
        for x in tokens[k + 1:]:  # the first country after the name, before the next person
            if x[0] == "person":
                break
            if x[0] == "country":
                after = x[1]
                break
        before = tokens[k - 1][1] if k and tokens[k - 1][0] in ("flag", "country") else ""
        people.append((t[1], t[2], after or before))
    if not people:  # names written without links: 'Haya Zayed ( EGY )'
        flag = next((x[1] for x in tokens if x[0] in ("flag", "country")), "")
        for part in re.split(r"<br\s*/?>", str(cell)):
            piece = BeautifulSoup(part, "lxml")
            for junk in piece.select(".flagicon, sup, style"):
                junk.decompose()
            name, _, code = _person(piece)
            if name and not _is_country(name, ref) and len(name.split()) >= 2:
                people.append((name, "", code or flag))
    return [(n, t, nation) for n, t, nation in people if n and not NO_MEDAL.match(n)]


def medal_appearances(table: Tag, year: int, url: str, path: list[str], ref: CountryReference,
                      skipped: list[str]) -> list[Appearance]:
    out, context, event = [], "", ""
    for row in table.select("tr")[1:]:
        cells = _cells(row)
        if len(cells) == 1:  # a sub-header row: 'Individual', 'Seniors', 'Junior', 'Men', 'Teams'
            context = cells[0].get_text(" ", strip=True)
            continue
        if len(cells) >= 4:
            # "Hoop details" / "Hoop [ 3 ]": the link to the results section and footnotes are not part of the name
            event = re.sub(r"\[.*?\]|\bdetails\b", "", cells[0].get_text(" ", strip=True)).strip()
            medal_cells = cells[1:4]
        else:  # a tie: the event cell spans this row too
            medal_cells = cells
        where = " / ".join(path + [context, event])
        if NOT_INDIVIDUAL.search(" ".join(path + [context])) or NOT_INDIVIDUAL.search(event) \
                or not INDIVIDUAL_EVENT.search(event):
            if where not in skipped:
                skipped.append(where)
            continue
        for cell in medal_cells:
            for name, title, nation in medalists(cell, ref):
                out.append(Appearance(year, "medal", name, title, nation, " / ".join(path), url, event=event))
    return out


def extract(html: str, title: str, year: int, url: str, competition: str,
            ref: CountryReference) -> tuple[list[Appearance], dict]:
    soup = BeautifulSoup(html, "lxml")
    general = "Rhythmic" not in title  # a general Pan American championship: read only its rhythmic section
    apps: list[Appearance] = []
    used, skipped = [], []
    for table in soup.select("table.wikitable"):
        rows = table.select("tr")
        if not rows:
            continue
        path = section_path(table)
        if general and not any("rhythmic" in p.lower() for p in path):
            continue
        header = [re.sub(r"\s+", " ", c.get_text(" ", strip=True)).lower() for c in _cells(rows[0])]
        if {"gold", "silver", "bronze"} <= set(header) and "nation" not in header and "rank" not in header:
            found = medal_appearances(table, year, url, path, ref, skipped)
            used.append({"table": " / ".join(path), "kind": "medal", "rows": len(found)})
            apps += found
            continue
        stage = _stage(path[-1] if path else "")
        if not stage and path and APPARATUS_FINAL.fullmatch(path[-1].strip()):
            # an apparatus final (8 gymnasts): many continental articles have no qualification table, so a gymnast
            # who competed only in finals (Lala Kramarenko, Europe 2021: team + hoop final) is found only here
            stage = "final"
        if not stage or any(NOT_INDIVIDUAL.search(p) for p in path[:-1]):
            continue
        if header and TEAM_LAYOUT.match(header[0]):
            people = _parse_team_layout(table)
        else:
            name_i = next((i for i, h in enumerate(header) if h in NAME_HEADERS), None)
            if name_i is None:  # group table
                continue
            nation_i = next((i for i, h in enumerate(header) if h in NATION_HEADERS), None)
            people = _parse_flat(table, name_i, nation_i, [])
        used.append({"table": " / ".join(path), "kind": stage, "rows": len(people)})
        apps += [Appearance(year, stage, n, link, nat, " / ".join(path), url) for n, link, nat, _ in people]
    for a in apps:
        a.competition = competition
    return apps, {"tables": used, "skipped_events": skipped}


FIELDS = list(Appearance.__dataclass_fields__)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--refresh", action="store_true", help="re-download the articles")
    ap.add_argument("--out", type=Path, default=INTERIM)
    args = ap.parse_args(argv)

    client, ref = WikiClient(), load_reference()
    apps: list[Appearance] = []
    report = []
    for competition, (index, pattern) in INDEXES.items():
        for year, title in championship_titles(client.get_page(index, refresh=args.refresh).html, pattern):
            page = client.get_page(title, refresh=args.refresh)
            found, info = extract(page.html, title, year, page.url, competition, ref)
            apps += found
            stages = {s: sum(a.stage == s for a in found) for s in ("qualification", "all-around", "final", "medal")}
            report.append({"competition": competition, "year": year, "page": page.title, "revid": page.revid,
                           **stages, **info})
            print(f"{competition:7} {year}: {len(found):3} names {stages}")

    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "cont_appearances.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(asdict(a) for a in apps)
    (args.out / "cont_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{len(report)} championships, {len(apps)} appearances")
    return 0


if __name__ == "__main__":
    sys.exit(main())
