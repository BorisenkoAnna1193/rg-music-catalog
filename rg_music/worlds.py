"""Collect the list of individual gymnasts from the World Championships articles.

For every championship linked from "Rhythmic Gymnastics World Championships" we take
the individual qualification table (if the article has one) and the individual
all-around final, and read the gymnast names from them. A name in a table is
usually a link to the gymnast's own article; that link (resolved through
redirects to a canonical title + pageid) is the identity key, so "Yevgenia" and
"Evgenia" spellings of one linked person fall into one row.

Usage:
    python -m rg_music.worlds [--refresh]
Output (data/interim/):
    wc_appearances.csv   one row per gymnast per table (raw layer, nothing merged)
    wc_gymnasts.csv      one row per gymnast: page, nations, years, all spellings
    wc_name_review.csv   rows for the owner to check: spelling variants of one page and
                         look-alike names on different pages / without a page
    wc_country_mapping.csv  every country text found in the tables -> country reference row, how it
                         matched (code/exact/contained/fuzzy/none); check everything but code/exact
    wc_report.json       tables used per championship, counts, skipped rows
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import unquote

from bs4 import BeautifulSoup, Tag

from .countries import CountryReference, load_reference
from .wiki_client import WikiClient

INDEX_TITLE = "Rhythmic Gymnastics World Championships"
INTERIM = Path("data/interim")
NAME_HEADERS = {"name", "gymnast", "gymnasts"}
NATION_HEADERS = {"nation", "country"}
TEAM_LAYOUT = re.compile(r"nation\s*/\s*gymnasts?", re.I)
JUNK_NAME = re.compile(r"^(other\b.*|\.+|…|-+|—)$", re.I)  # placeholder rows like "Other non-Team", "..."
SIMILAR = 0.9  # name similarity above which two different gymnasts go to the review sheet


@dataclass
class Appearance:
    year: int
    stage: str  # qualification | all-around
    name: str
    wiki_title: str  # linked article title as written in the table, "" if no link
    nation: str  # exactly as in the table (link title, flag name or IOC code)
    table_heading: str
    source_url: str
    gymnast_key: str = ""  # filled by aggregate(): which gymnast row this appearance belongs to
    country_id: str = ""  # filled by attach_countries(): row of the ISO-based country reference
    country: str = ""  # short name from the reference
    country_match: str = ""  # how the nation text was matched: code | exact | contained | fuzzy | none
    competition: str = "world"  # world | europe | asia | africa | panam (continental.py)
    event: str = ""  # medal tables only: the event of the medal (All-Around, Hoop...)


# ---------------------------------------------------------------- index
def championship_pages(index_html: str) -> list[tuple[int, str]]:
    """(year, article title) for every championship in the first table of the index page."""
    soup = BeautifulSoup(index_html, "lxml")
    out = []
    for row in soup.select("table.wikitable")[0].select("tr")[1:]:
        year = row.find(["th", "td"]).get_text(strip=True)
        link = row.select_one('a[href*="Championships"]')
        if link and year.isdigit() and "redlink" not in link["href"]:
            out.append((int(year), unquote(link["href"].split("/wiki/")[1]).replace("_", " ")))
    return out


# ---------------------------------------------------------------- cells
def _cells(row: Tag) -> list[Tag]:
    return row.find_all(["th", "td"], recursive=False)


def _link_title(cell: Tag) -> str:
    """Title of the first article link in a cell (no files, no red links)."""
    for a in cell.select('a[href^="/wiki/"]'):
        target = a["href"][len("/wiki/"):]
        if not target.startswith(("File:", "Image:")):
            return unquote(target.split("#")[0]).replace("_", " ")
    return ""


def _person(cell: Tag) -> tuple[str, str, str]:
    """(name, article title, IOC code) from a name cell; 'Basma Ouatay ( MAR )' -> code MAR."""
    for junk in cell.select("sup, style"):
        junk.decompose()
    name = re.sub(r"\s+", " ", cell.get_text("")).strip()
    code = ""
    if m := re.search(r"\(\s*([A-Z]{3})\s*\)$", name):
        code, name = m.group(1), name[:m.start()].strip()
    name = name.rstrip("*†‡#^ ").strip()
    if JUNK_NAME.match(name):
        name = ""
    return name, _link_title(cell), code


def _nation(cell: Tag | None) -> str:
    if cell is None:
        return ""
    if title := _link_title(cell):
        return title
    img = cell.select_one("img[src*='Flag_of_']")
    if img and (m := re.search(r"Flag_of_(.+?)\.svg", unquote(img["src"]))):
        return m.group(1).replace("_", " ")
    return re.sub(r"\s+", " ", cell.get_text(" ")).strip()


def _stage(heading: str) -> str:
    h = heading.lower()
    if "olympic" in h:
        return ""
    if "qualif" in h:
        return "qualification"
    if re.search(r"all-?\s?around", h) and not re.search(r"team|group|combined", h):
        return "all-around"
    return ""


# ---------------------------------------------------------------- tables
def _parse_flat(table: Tag, name_i: int, nation_i: int | None, skipped: list) -> list[tuple[str, str, str, str]]:
    out = []
    for row in table.select("tr")[1:]:
        cells = _cells(row)
        if len(cells) <= name_i:
            skipped.append(row.get_text(" ", strip=True)[:60])
            continue
        name, link, code = _person(cells[name_i])
        if not name or name.replace(".", "").isdigit():
            continue
        nation = _nation(cells[nation_i]) if nation_i is not None and nation_i < len(cells) else ""
        out.append((name, link, nation or code, ""))
    return out


def _parse_team_layout(table: Tag) -> list[tuple[str, str, str, str]]:
    """'Nation/Gymnasts' table: a flag row per team, then its gymnasts; individuals come last
    with the country as '( MAR )' after the name."""
    out, country, individuals = [], "", False
    for row in table.select("tr")[1:]:
        cells = _cells(row)
        if not cells:
            continue
        first = cells[0]
        if first.select_one(".flagicon, img[src*='Flag_of_']"):
            country, individuals = _nation(first), False
            continue
        name, link, code = _person(first)
        if not name:
            continue
        individuals = individuals or bool(code)
        out.append((name, link, code if individuals else country, ""))
    return out


def extract_appearances(html: str, year: int, source_url: str) -> tuple[list[Appearance], list[dict]]:
    soup = BeautifulSoup(html, "lxml")
    found, used = [], []
    for table in soup.select("table.wikitable"):
        heading_tag = table.find_previous(["h2", "h3", "h4"])
        heading = heading_tag.get_text(" ", strip=True) if heading_tag else ""
        stage = _stage(heading)
        rows = table.select("tr")
        if not stage or not rows:
            continue
        header = [re.sub(r"\s+", " ", c.get_text(" ", strip=True)).lower() for c in _cells(rows[0])]
        skipped: list = []
        if header and TEAM_LAYOUT.match(header[0]):
            people = _parse_team_layout(table)
        else:
            name_i = next((i for i, h in enumerate(header) if h in NAME_HEADERS), None)
            if name_i is None:  # group / team table
                continue
            nation_i = next((i for i, h in enumerate(header) if h in NATION_HEADERS), None)
            people = _parse_flat(table, name_i, nation_i, skipped)
        used.append({"heading": heading, "stage": stage, "rows": len(people), "skipped_rows": skipped})
        found += [Appearance(year, stage, n, link, nat, heading, source_url) for n, link, nat, _ in people]
    return found, used


# ---------------------------------------------------------------- names
_FOLD = str.maketrans({"ł": "l", "Ł": "L", "ø": "o", "Ø": "O", "đ": "d", "Đ": "D", "ß": "ss", "æ": "ae", "Æ": "AE"})


def _ascii(s: str) -> str:
    return unicodedata.normalize("NFKD", s.translate(_FOLD)).encode("ascii", "ignore").decode()


_TRANSLIT = [("ya", "ia"), ("yu", "iu"), ("ye", "e"), ("yo", "e"), ("ja", "ia"), ("ju", "iu"),
             ("je", "e"), ("kh", "h"), ("w", "v"), ("y", "i"), ("j", "i")]


def name_key(name: str) -> str:
    """Spelling-insensitive key: 'Yevgenia Kanayeva' and 'Evgenia Kanaeva' collide."""
    s = _ascii(name).lower()
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"[^a-z ]", " ", s)
    for a, b in _TRANSLIT:
        s = s.replace(a, b)
    s = re.sub(r"(.)\1+", r"\1", s)
    return " ".join(sorted(s.split()))


def _plain(name: str) -> str:
    return _ascii(re.sub(r"\(.*?\)", "", name)).lower().strip()


# ---------------------------------------------------------------- aggregate
def _country_key(a: Appearance) -> str:
    return a.country_id or a.nation


def attach_countries(apps: list[Appearance], ref: CountryReference) -> list[dict]:
    """Fill country_id / country / country_match on every appearance; return the mapping for review."""
    mapping: dict[str, dict] = {}
    for a in apps:
        m = ref.match(a.nation)
        a.country_id, a.country, a.country_match = m.country_id, m.name, m.method
        row = mapping.setdefault(a.nation, {"nation_in_table": a.nation, "country_id": m.country_id, "country": m.name,
                                            "method": m.method, "score": m.score, "appearances": 0})
        row["appearances"] += 1
    return sorted(mapping.values(), key=lambda r: (r["method"] in {"exact", "code"}, r["nation_in_table"].lower()))


def aggregate(apps: list[Appearance], resolved: dict[str, tuple[str, int | None]]) -> list[dict]:
    groups: dict[str, list[Appearance]] = defaultdict(list)
    for a in apps:
        page, pageid = resolved.get(a.wiki_title, ("", None)) if a.wiki_title else ("", None)
        key = f"page:{pageid}" if pageid else f"name:{name_key(a.name)}|{_country_key(a)}"
        groups[key].append(a)
    merged = _merge_unlinked(groups, resolved)

    rows = []
    for key, items in groups.items():
        for a in items:
            a.gymnast_key = key
        spell = Counter(a.name for a in items)
        all_years = sorted({a.year for a in items})
        years = sorted({a.year for a in items if a.competition == "world"})  # World Championship years only
        nations = Counter(a.country or a.nation for a in items if a.country or a.nation)
        page, pageid = resolved.get(items[0].wiki_title, ("", None)) if items[0].wiki_title else ("", None)
        rows.append({
            "gymnast_key": key,
            # the World Championship spelling stays the name; continental tables only name the gymnasts who never
            # competed at Worlds (they often drop diacritics: 'Kutkaite' for 'Kutkaitė')
            "display_name": (Counter(a.name for a in items if a.competition == "world") or spell).most_common(1)[0][0],
            "wiki_page": page if pageid else "",
            "pageid": pageid or "",
            "has_page": bool(pageid),
            "nations": " | ".join(n for n, _ in nations.most_common()),
            "first_year": all_years[0], "last_year": all_years[-1], "championships": len(years),
            "years": ",".join(map(str, years)),
            "events": events_summary(items),
            "spellings": " | ".join(f"{s} ({','.join(str(y) for y in sorted({a.year for a in items if a.name == s}))})"
                                    for s, _ in spell.most_common()),
            "n_spellings": len({_plain(s) for s in spell}),
            "merged_by_name": key in merged,
        })
    return sorted(rows, key=lambda r: (r["display_name"].lower()))


COMPETITIONS = ["world", "europe", "asia", "africa", "panam"]


def events_summary(items) -> str:
    """'world 2019,2021; europe 2020' - every championship of one gymnast, World Championships first."""
    by: dict[str, set[int]] = defaultdict(set)
    for a in items:
        comp = a.competition if isinstance(a, Appearance) else a.get("competition") or "world"
        by[comp].add(int(a.year if isinstance(a, Appearance) else a["year"]))
    return "; ".join(f"{c} {','.join(map(str, sorted(by[c])))}" for c in COMPETITIONS if c in by)


def load_continental(path: Path) -> list[Appearance]:
    """Appearances written by continental.py (cont_appearances.csv); none if it has not been run."""
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [Appearance(**{**{k: v for k, v in r.items() if k in Appearance.__dataclass_fields__},
                              "year": int(r["year"])}) for r in csv.DictReader(f)]


def _merge_unlinked(groups: dict[str, list[Appearance]], resolved: dict[str, tuple[str, int | None]]) -> set[str]:
    """Attach rows without a link to the one linked gymnast with the same name key and nation.

    A person is often linked in one year's table and plain text in another. Ambiguous
    matches (several candidates) are left alone and show up in the review sheet.
    """
    index: dict[str, list[str]] = defaultdict(list)
    for key, items in groups.items():
        if key.startswith("page:"):
            names = {a.name for a in items} | {resolved[items[0].wiki_title][0]}
            for k in {name_key(n) for n in names}:
                index[k].append(key)
    merged = set()
    for key in [k for k in groups if k.startswith("name:")]:
        items = groups[key]
        nkey, _, nation = key[len("name:"):].partition("|")
        candidates = [c for c in index.get(nkey, [])
                      if not nation or nation in {_country_key(a) for a in groups[c]}]
        if len(candidates) == 1:
            groups[candidates[0]].extend(groups.pop(key))
            merged.add(candidates[0])
    return merged


def review_rows(gymnasts: list[dict]) -> list[dict]:
    """Spelling variants within one page + look-alike names across different rows."""
    review, group = [], 0
    for g in gymnasts:
        title = re.sub(r"\s*\(.*?\)$", "", g["wiki_page"]) if g["wiki_page"] else ""
        spellings = {s.split(" (")[0] for s in g["spellings"].split(" | ")} | ({title} if title else set())
        if len({_plain(s) for s in spellings}) > 1:
            group += 1
            # translit_only: Yevgenia/Evgenia-type differences; different_name: other words or extra surnames
            kind = "translit_only" if len({name_key(s) for s in spellings}) == 1 else "different_name"
            review.append({"group": group, "reason": "spelling_variants", "similarity": "", "kind": kind,
                           **_review_cols(g)})

    blocks: dict[str, list[int]] = defaultdict(list)
    keys = [name_key(g["display_name"]) for g in gymnasts]
    for i, k in enumerate(keys):
        for token in k.split():
            blocks[token[:3]].append(i)
    seen = set()
    for members in blocks.values():
        for x, i in enumerate(members):
            for j in members[x + 1:]:
                if (i, j) in seen or gymnasts[i]["gymnast_key"] == gymnasts[j]["gymnast_key"]:
                    continue
                seen.add((i, j))
                m = SequenceMatcher(None, keys[i], keys[j])
                if m.real_quick_ratio() >= SIMILAR and m.quick_ratio() >= SIMILAR and m.ratio() >= SIMILAR:
                    group += 1
                    for g in (gymnasts[i], gymnasts[j]):
                        review.append({"group": group, "reason": "possible_duplicate",
                                       "similarity": round(m.ratio(), 2), "kind": "", **_review_cols(g)})
    return review


def _review_cols(g: dict) -> dict:
    return {
        "display_name": g["display_name"], "wiki_page": g["wiki_page"], "nations": g["nations"],
        "years": g["years"], "spellings": g["spellings"], "gymnast_key": g["gymnast_key"],
        "decision": "", "canonical_name": "",
    }


REVIEW_FIELDS = ["group", "reason", "kind", "similarity", "display_name", "wiki_page", "nations", "years",
                 "spellings", "gymnast_key", "decision", "canonical_name"]
GYMNAST_FIELDS = ["gymnast_key", "display_name", "wiki_page", "pageid", "has_page", "nations", "first_year",
                  "last_year", "championships", "years", "events", "spellings", "n_spellings", "merged_by_name"]


def _write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    # utf-8-sig: with a BOM Excel shows "Jovanović" correctly instead of "JovanoviƒЗ"
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--refresh", action="store_true", help="re-download the articles")
    ap.add_argument("--out", type=Path, default=INTERIM)
    ap.add_argument("--no-continental", action="store_true",
                    help="World Championships only (without data/interim/cont_appearances.csv)")
    args = ap.parse_args(argv)

    client = WikiClient()
    championships = championship_pages(client.get_page(INDEX_TITLE, refresh=args.refresh).html)
    apps: list[Appearance] = []
    report = []
    for year, title in championships:
        page = client.get_page(title, refresh=args.refresh)
        found, used = extract_appearances(page.html, year, page.url)
        apps += found
        report.append({"year": year, "page": page.title, "revid": page.revid, "appearances": len(found), "tables": used})
        print(f"{year}: {len(found):4} names  {[(t['stage'], t['rows']) for t in used]}")

    if not args.no_continental:  # step 24: the list is the union of World and continental championships
        cont = load_continental(args.out / "cont_appearances.csv")
        print(f"+ {len(cont)} continental appearances")
        apps += cont
    mapping = attach_countries(apps, load_reference())
    resolved = client.resolve_titles([a.wiki_title for a in apps if a.wiki_title])
    gymnasts = aggregate(apps, resolved)
    review = review_rows(gymnasts)

    args.out.mkdir(parents=True, exist_ok=True)
    _write_csv(args.out / "wc_appearances.csv", list(Appearance.__dataclass_fields__), [asdict(a) for a in apps])
    _write_csv(args.out / "wc_country_mapping.csv",
               ["nation_in_table", "country_id", "country", "method", "score", "appearances"], mapping)
    _write_csv(args.out / "wc_gymnasts.csv", GYMNAST_FIELDS, gymnasts)
    _write_csv(args.out / "wc_name_review.csv", REVIEW_FIELDS, review)
    (args.out / "wc_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    linked = sum(g["has_page"] for g in gymnasts)
    print(f"\n{len(championships)} championships, {len(apps)} appearances -> {len(gymnasts)} gymnasts "
          f"({linked} with an article, {len(gymnasts) - linked} without); {len(review)} review rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
