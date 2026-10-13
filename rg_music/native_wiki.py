"""Probe: would the gymnast's home-language Wikipedia add music to the English one? (owner's idea, 2026-10-13)

For every gymnast with an English article: the article in the language of her country (via the English article's
language links), fetched politely (1 request per second, cached under data/raw/<lang>/), and searched for music: tables
whose header names music in that language ("Музыка", "Música", "Musica"...), the number of their data rows, and a
section heading about music. Former Soviet countries are also checked in Russian, where articles are often fuller.
Nothing is parsed into routines here: this only measures what the second language would add.

Usage:
    python -m rg_music.native_wiki
Reads  data/interim/wc_gymnasts_final.csv, routines_raw.csv, data/manual/gymnast_country_overrides.csv
Writes data/interim/native_wiki_probe.csv
"""

from __future__ import annotations

import csv
import re
import sys
from collections import Counter
from pathlib import Path

from bs4 import BeautifulSoup

from rg_music.wiki_client import WikiClient, WikiError

INTERIM = Path("data/interim")
OVERRIDES = Path("data/manual/gymnast_country_overrides.csv")
LANG = {
    "BGR": "bg", "ESP": "es", "RUS": "ru", "SUHH": "ru", "UKR": "uk", "DEU": "de", "DDDE": "de", "AUT": "de", "CHE": "de",
    "ITA": "it", "SMR": "it", "BLR": "be", "CHN": "zh", "AZE": "az", "ISR": "he", "JPN": "ja", "POL": "pl", "UZB": "uz",
    "KAZ": "kk", "ROU": "ro", "MDA": "ro", "BRA": "pt", "PRT": "pt", "AGO": "pt", "CPV": "pt", "FRA": "fr", "SVN": "sl",
    "CZE": "cs", "CSHH": "cs", "GRC": "el", "CYP": "el", "FIN": "fi", "KOR": "ko", "PRK": "ko", "EGY": "ar", "MEX": "es",
    "ARG": "es", "COL": "es", "CHL": "es", "VEN": "es", "GTM": "es", "BOL": "es", "PRI": "es", "HUN": "hu", "MYS": "ms",
    "EST": "et", "YUCS": "sr", "SRB": "sr", "MNE": "sr", "LTU": "lt", "GEO": "ka", "NOR": "no", "LVA": "lv", "SWE": "sv",
    "TUR": "tr", "BEL": "nl", "DNK": "da", "AND": "ca", "MKD": "mk", "HRV": "hr", "THA": "th", "KGZ": "ky", "LAO": "lo",
}
EX_USSR = {"BLR", "UKR", "AZE", "UZB", "KAZ", "GEO", "KGZ", "MDA", "LTU", "LVA", "EST", "SUHH"}
MUSIC = re.compile(r"музык|музик|музыч|muzy|música|musica|musique|musik|muziek|zene|muusika|musiikki|muzika|mūzika|glasba"
                   r"|glazba|hudba|müzik|musiqi|мусиқ|μουσικ|מוזיק|موسيق|音楽|曲|音乐|配乐|음악|მუსიკ|ดนตรี|melodi|muzică|muzica|música",
                   re.I)


def music_in(html: str) -> tuple[int, int, bool]:
    """-> (music tables, their data rows, a section heading about music)."""
    soup = BeautifulSoup(html, "html.parser")
    tables = rows = 0
    for table in soup.find_all("table"):
        trs = table.find_all("tr")
        head = " ".join(c.get_text(" ", strip=True) for tr in trs[:2] for c in tr.find_all(["th", "td"]))
        if MUSIC.search(head):
            tables += 1
            rows += sum(1 for tr in trs[1:] if tr.find("td"))
    section = any(MUSIC.search(h.get_text(" ", strip=True)) for h in soup.find_all(["h2", "h3", "h4"]))
    return tables, rows, section


def main() -> int:
    read = lambda p: list(csv.DictReader(p.open(encoding="utf-8-sig")))  # noqa: E731
    overrides = {r["wiki_page"]: r["country_id"] for r in read(OVERRIDES)} if OVERRIDES.exists() else {}
    gymnasts = [g for g in read(INTERIM / "wc_gymnasts_final.csv") if g["wiki_page"]]
    en_rows = Counter(r["gymnast_page"] for r in read(INTERIM / "routines_raw.csv") if r["music"])
    en = WikiClient()
    links = en.langlinks([g["wiki_page"] for g in gymnasts])
    clients: dict[str, WikiClient] = {}
    out = []
    for i, g in enumerate(gymnasts, 1):
        country = overrides.get(g["wiki_page"], g["country_id"])
        page_links = links.get(g["wiki_page"], {})
        for lang in [LANG.get(country)] + (["ru"] if country in EX_USSR and LANG.get(country) != "ru" else []):
            if not lang or lang not in page_links:
                if lang:
                    out.append({"wiki_page": g["wiki_page"], "country": country, "lang": lang, "native_title": "",
                                "en_rows": en_rows[g["wiki_page"]], "tables": "", "rows": "", "section": "", "status": "no article"})
                continue
            client = clients.setdefault(lang, WikiClient(lang=lang))
            try:
                page = client.get_page(page_links[lang])
                tables, rows, section = music_in(page.html)
                status = "ok"
            except WikiError as exc:
                tables, rows, section, status = "", "", "", f"error: {exc}"
            out.append({"wiki_page": g["wiki_page"], "country": country, "lang": lang, "native_title": page_links[lang],
                        "en_rows": en_rows[g["wiki_page"]], "tables": tables, "rows": rows, "section": section, "status": status})
        if i % 50 == 0:
            print(f"  {i}/{len(gymnasts)}", flush=True)
    fields = ["wiki_page", "country", "lang", "native_title", "en_rows", "tables", "rows", "section", "status"]
    with (INTERIM / "native_wiki_probe.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(out)
    found = [r for r in out if r["status"] == "ok"]
    print(f"{len(gymnasts)} gymnasts; home-language articles fetched: {len(found)}; with a music table: "
          f"{sum(1 for r in found if r['tables'])}; new music for gymnasts without any in English: "
          f"{len({r['wiki_page'] for r in found if r['rows'] and not r['en_rows']})}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
