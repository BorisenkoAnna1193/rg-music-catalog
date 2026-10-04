"""Russian names of gymnasts, taken from Wikidata (no invented transliteration).

For every gymnast with a Wikipedia article: the Russian Wikidata label, or - when there is no label -
the title of the Russian Wikipedia article. Only names written in Cyrillic are accepted. They come
in several shapes ("Солдатова, Александра Сергеевна", "Александра Кирой-Богатырёва"), so the name is
cleaned to "Given Surname" without the patronymic. A gymnast without a Russian name keeps an empty
`name_ru`; the dashboard then shows the Latin name.

Usage:
    python -m rg_music.names_ru
Reads  data/interim/wc_gymnasts_final.csv
Writes data/interim/gymnast_names_ru.csv  wiki_page, wikidata_id, name_ru_raw, name_ru, name_ru_source,
                                          needs_review (more than two words left: check by hand)
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

from .fig_names import Fetcher

INTERIM = Path("data/interim")
FIELDS = ["wiki_page", "wikidata_id", "name_ru_raw", "name_ru", "name_ru_source", "needs_review"]
CYRILLIC = re.compile("[А-Яа-яЁё]")
PATRONYMIC = re.compile(r"(ович|евич|ьич|овна|евна|ична|инична|кызы|гызы|оглы)$", re.I)


def clean_ru_name(raw: str) -> tuple[str, bool]:
    """('Given Surname', needs_review). Handles 'Surname, Given Patronymic' and a trailing '(gymnast)'."""
    name = re.sub(r"\s*\([^)]*\)\s*$", "", raw).strip()
    if "," in name:
        surname, rest = (p.strip() for p in name.split(",", 1))
        words = [w for w in rest.split() if not PATRONYMIC.search(w)] + surname.split()
    else:  # the patronymic stands in the middle; the last word is the surname even if it ends in -ович/-евич
        tokens = name.split()
        words = [w for i, w in enumerate(tokens) if not (0 < i < len(tokens) - 1 and PATRONYMIC.search(w))]
    return " ".join(words), len(words) > 2


def russian_name(label: str, ruwiki_title: str) -> tuple[str, str]:
    """(raw name, source) preferring the Wikidata label; only Cyrillic names count."""
    if CYRILLIC.search(label):
        return label, "wikidata_label"
    if CYRILLIC.search(ruwiki_title):
        return ruwiki_title, "ruwiki_title"
    return "", ""


def main() -> int:
    final = list(csv.DictReader((INTERIM / "wc_gymnasts_final.csv").open(encoding="utf-8-sig")))
    titles = sorted({g["wiki_page"] for g in final if g["wiki_page"]})
    fetcher = Fetcher()
    rows = []
    for i in range(0, len(titles), 50):
        data = fetcher.wikidata(action="wbgetentities", sites="enwiki", titles="|".join(titles[i:i + 50]),
                                props="labels|sitelinks", languages="ru", sitefilter="enwiki|ruwiki")
        for entity in data["entities"].values():
            if "missing" in entity or "enwiki" not in entity.get("sitelinks", {}):
                continue
            raw, source = russian_name(entity.get("labels", {}).get("ru", {}).get("value", ""),
                                       entity.get("sitelinks", {}).get("ruwiki", {}).get("title", ""))
            name, review = clean_ru_name(raw) if raw else ("", False)
            rows.append({"wiki_page": entity["sitelinks"]["enwiki"]["title"], "wikidata_id": entity["id"],
                         "name_ru_raw": raw, "name_ru": name, "name_ru_source": source,
                         "needs_review": review})
    rows.sort(key=lambda r: r["wiki_page"])
    with (INTERIM / "gymnast_names_ru.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    have = sum(bool(r["name_ru"]) for r in rows)
    print(f"{len(rows)} gymnasts with a Wikidata item, Russian name for {have} "
          f"({sum(r['needs_review'] for r in rows)} to check by hand)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
