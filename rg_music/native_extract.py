"""Second source: the music tables of the gymnast's home-language Wikipedia, kept as they are (step 19).

native_wiki.py found which home-language articles have a music table; this step reads those tables. The probe counted
any table whose header mentions music, so navigation boxes slipped in (Kabaeva's Russian article: members of the Duma;
Shin Soo-ji's Korean one: a TV show). Here only ``wikitable`` tables whose header names a year, an apparatus and music in
that language are read, so those false positives drop out.

The Spanish tables add a category to the year ("1994 (Individual júnior)", "1989 (Conjunto 1.ª categoría)") and use
Spanish apparatus names ("Aro", "3 aros y 2 pelotas", "Ejercicio de exhibición (Manos libres)"). Both are translated by
the vocabulary below; a group routine (a number of apparatus) is marked ``group`` and is not merged into the individual
catalogue. The music cell is NOT translated here: it is Spanish prose ("«Taquito militar», tango compuesto por Mariano
Mores."), so its English wording comes from data/manual/native_music_en.csv, applied in merge.py.

Usage:
    python -m rg_music.native_extract
Reads  data/interim/native_wiki_probe.csv
Writes data/interim/native_routines_raw.csv, native_extract_report.json
"""

from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import NamedTuple

from bs4 import BeautifulSoup

from rg_music.tables import expand_table
from rg_music.wiki_client import WikiClient

INTERIM = Path("data/interim")
FIELDS = ["gymnast_page", "lang", "native_title", "revid", "table_index", "row_index", "year", "apparatus", "music",
          "source_url"]

HEADERS = {  # column -> words of its header, per language
    "es": {"year": ("año",), "apparatus": ("aparato",), "music": ("música",)},
    "ru": {"year": ("год",), "apparatus": ("предмет",), "music": ("музык",)},
}
APPARATUS = {
    "es": {"aro": "Hoop", "aros": "Hoop", "pelota": "Ball", "pelotas": "Ball", "mazas": "Clubs", "cinta": "Ribbon",
           "cintas": "Ribbon", "cuerda": "Rope", "cuerdas": "Rope", "manos libres": "Free hands",
           "ejercicio de exhibición": "Gala", "pañuelo": "scarf", "pañuelos": "scarves", "silla": "chair"},
    "ru": {"обруч": "Hoop", "мяч": "Ball", "булавы": "Clubs", "лента": "Ribbon", "скакалка": "Rope",
           "без предмета": "Free hands", "gala": "Gala"},
}
CATEGORY = {  # the age category the source states next to the year
    "individual júnior": "junior", "individual infantil": "pre-junior", "individual alevín": "pre-junior",
    "categoría alevín": "pre-junior", "individual infantil y júnior": "pre-junior and junior",
}
CONTEXT = {  # words of the bracketed note after an apparatus ("Cinta (Inicio de temporada)") and of a gala's note
    "es": [(r"^Inicio de temporada$", "start of season"), (r"^JJ\. ?OO\. de (\w+)$", r"Olympics \1"),
           (r"\bGala 20\.º Aniversario de la Medalla de Oro en Atlanta '96", "the gala for the 20th anniversary of the "
            "Atlanta '96 gold medal"),
           (r"\bconjunto búlgaro y 70 exgimnastas de la selección española que fueron entradas por Emilia Boneva",
            "the Bulgarian group and 70 former Spanish team gymnasts coached by Emilia Boneva"),
           (r"\bgimnastas del Club\b", "gymnasts of Club"), (r"\bdel Club\b", "of Club"), (r"\bjunto al pianista\b", "with pianist"),
           (r"\bla cantante\b", "singer"), (r"\buna silla\b", "a chair"),
           (r"\bjunto (?:a|al|con)\b", "with"), (r"\bcon\b", "with"), (r"\ben\b", "at"), (r"\by\b", "and"),
           (r"\bGala de Navidad\b", "Christmas Gala"), (r"^primera versión$", "first"), (r"^segunda versión$", "second")],
    "ru": [(r"^первая версия$", "first"), (r"^вторая версия$", "second"), (r"^третья версия$", "third"),
           (r"^(\d)$", lambda m: {"1": "first", "2": "second", "3": "third"}[m.group(1)])],
}
PLACES = {"Sídney": "Sydney 2000", "Atenas": "Athens 2004", "Pekín": "Beijing 2008", "Londres": "London 2012"}
COUNT = re.compile(r"^\d+\s+\w+")  # "5 cintas", "3 aros y 2 pelotas": a group routine


class Year(NamedTuple):
    text: str        # the year or season alone ("1995-1996"), as merge.py expects it
    category: str    # junior / pre-junior / group / "" (none stated)


class Apparatus(NamedTuple):
    text: str        # in English, as the English tables write it: "Ribbon (start of season)", "Gala (Free hands)"
    kind: str        # individual / group / unknown


def split_year(text: str) -> Year:
    """ "1994 (Individual júnior)" -> ("1994", "junior"); "2001 - 2002" -> ("2001-2002", "")."""
    m = re.match(r"^(.*?)\s*\((.*)\)\s*$", text.strip())
    year, note = (m.group(1), m.group(2).strip()) if m else (text.strip(), "")
    year = re.sub(r"\s*[-–]\s*", "-", year)
    if note.lower().startswith("conjunto"):
        return Year(year, "group")
    return Year(year, CATEGORY.get(note.lower(), note))


def _context(note: str, lang: str) -> str:
    for pattern, english in CONTEXT.get(lang, []):
        note = re.sub(pattern, english, note)
    for es, en in PLACES.items():
        note = note.replace(f"Olympics {es}", f"{en} Olympics")
    return _short_company(note)


def _short_company(note: str) -> str:
    """ "with A, B, C, D and E at Euskalgym" -> "with A, B and others at Euskalgym": a gala note is shown on a card."""
    m = re.match(r"^(.*?\bwith )(.*?)((?: at .*)?)$", note)
    if not m:
        return note
    names = [n.strip() for n in re.split(r",(?: and)?| and ", m.group(2)) if n.strip()]
    return note if len(names) <= 3 else f"{m.group(1)}{names[0]}, {names[1]} and others{m.group(3)}"


def translate_apparatus(text: str, lang: str) -> Apparatus:
    """Home-language apparatus cell -> the English wording; "" kind unknown when the vocabulary has no such word."""
    words = APPARATUS.get(lang, {})
    text = re.sub(r"\s+", " ", text.strip())
    if COUNT.match(text):
        return Apparatus(text, "group")
    m = re.match(r"^([^()]*)(?:\((.*?)\))?\s*(.*)$", text)
    head, inner, tail = m.group(1).strip(), (m.group(2) or "").strip(), m.group(3).strip()
    name = words.get(head.lower())
    if not name:
        return Apparatus(text, "unknown")
    items = [words.get(i.strip().lower()) for i in inner.split(",") if i.strip()]
    if name == "Gala" and items and all(items):  # "Ejercicio de exhibición (Manos libres, cinta) junto a X en Euskalgym"
        parts = [", ".join(items)] + ([_context(tail, lang)] if tail else [])
        return Apparatus(f"Gala ({'; '.join(p for p in parts if p)})" if any(parts) else "Gala", "individual")
    note = "; ".join(p for p in [_context(inner, lang), _context(tail, lang)] if p)
    return Apparatus(f"{name} ({note})" if note else name, "individual")


def _column(headers: list[str], words: tuple[str, ...]) -> int | None:
    return next((i for i, h in enumerate(headers) if any(w in h for w in words)), None)


def native_rows(html: str, lang: str) -> list[dict]:
    """Rows of the music tables of one home-language article: table_index, row_index, year, apparatus, music as they are."""
    soup = BeautifulSoup(html, "lxml")
    out = []
    for t_idx, table in enumerate(soup.select("table.wikitable")):
        grid = expand_table(table)
        if not grid:
            continue
        headers = [text.lower() for text, _ in grid[0]]
        cols = {k: _column(headers, words) for k, words in HEADERS[lang].items()}
        if None in cols.values():
            continue
        for r_idx, row in enumerate(grid[1:]):
            cells = [text for text, _ in row]
            if len(cells) <= max(cols.values()):
                continue
            out.append({"table_index": t_idx, "row_index": r_idx, "year": cells[cols["year"]],
                        "apparatus": cells[cols["apparatus"]], "music": cells[cols["music"]]})
    return out


def main() -> int:
    probe = [r for r in csv.DictReader((INTERIM / "native_wiki_probe.csv").open(encoding="utf-8-sig"))
             if r["status"] == "ok" and r["tables"] not in ("", "0") and r["lang"] in HEADERS]
    clients: dict[str, WikiClient] = {}
    out, report = [], {"pages": {}, "rows": Counter()}
    for p in probe:
        page = clients.setdefault(p["lang"], WikiClient(lang=p["lang"])).get_page(p["native_title"])
        rows = native_rows(page.html, p["lang"])
        report["pages"][f"{p['lang']}:{page.title}"] = len(rows)
        for r in rows:
            out.append({"gymnast_page": p["wiki_page"], "lang": p["lang"], "native_title": page.title,
                        "revid": page.revid, **r, "source_url": page.url})
            report["rows"][p["lang"]] += 1
    with (INTERIM / "native_routines_raw.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(out)
    report["pages_without_a_routine_table"] = [k for k, n in report["pages"].items() if not n]
    (INTERIM / "native_extract_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(out)} rows from {sum(1 for n in report['pages'].values() if n)} home-language articles "
          f"({dict(report['rows'])}); no routine table: {', '.join(report['pages_without_a_routine_table']) or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
