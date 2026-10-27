"""Country reference (ISO 3166-1 + ISO 3166-3) and matching of free-text countries to it.

Reference tables (built from pycountry, plus a few sport-specific rows and aliases):
    data/reference/countries.csv         country_id, name (short), iso_name, alpha2, alpha3, alpha4,
                                         status (current | former | other), valid_until, note
    data/reference/country_aliases.csv   alias -> country_id, with the source of the alias

country_id is the ISO alpha-3 code for current countries and the ISO 3166-3 alpha-4 code for
former ones (SUHH = Soviet Union, CSHH = Czechoslovakia, DDDE = East Germany, YUCS = Yugoslavia).
`name` is the short everyday spelling used in this project ("Russia", "South Korea").

match() order: IOC/ISO 3-letter code -> exact alias -> a known name inside the text
-> most similar alias (difflib, cutoff FUZZY_CUTOFF) -> not found. The method and the score are
returned so that everything except "exact"/"code" can be reviewed.
The matcher ignores years and notes in brackets ("Venezuela (1930-2006)") and a leading "the";
whether a country existed in a given year is NOT checked ("Czech Republic" in 1971 stays CZE).

Usage:
    python -m rg_music.countries      # (re)build the two reference files
"""

from __future__ import annotations

import csv
import gettext
import re
import sys
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher, get_close_matches
from pathlib import Path

import pycountry

REFERENCE = Path("data/reference")
FUZZY_CUTOFF = 0.84
COUNTRY_FIELDS = ["country_id", "name", "name_ru", "iso_name", "alpha2", "alpha3", "alpha4", "status", "valid_until", "note"]
ALIAS_FIELDS = ["alias", "country_id", "source"]

# short everyday names where ISO's wording is awkward (everything else: common_name, or the part before the comma)
SHORT_NAMES = {
    "RUS": "Russia", "PRK": "North Korea", "CZE": "Czech Republic", "TWN": "Chinese Taipei",
    "TUR": "Turkey", "LAO": "Laos", "SYR": "Syria", "VNM": "Vietnam", "COD": "DR Congo",
    "CIV": "Ivory Coast", "CPV": "Cape Verde", "BRN": "Brunei", "VAT": "Vatican City",
    "SUHH": "Soviet Union", "DDDE": "East Germany", "CSHH": "Czechoslovakia", "YUCS": "Yugoslavia",
    "CSXX": "Serbia and Montenegro", "BYAA": "Byelorussian SSR",
}
# Russian short names where the ISO translation is an official long form
SHORT_NAMES_RU = {
    "RUS": "Россия", "KOR": "Южная Корея", "PRK": "Северная Корея", "TWN": "Китайский Тайбэй",
    "SUHH": "СССР", "CSHH": "Чехословакия", "DDDE": "ГДР", "YUCS": "Югославия", "CSXX": "Сербия и Черногория",
    "BYAA": "Белорусская ССР", "TUR": "Турция", "GBR": "Великобритания", "USA": "США", "VNM": "Вьетнам",
    "LAO": "Лаос", "SYR": "Сирия", "IRN": "Иран", "MDA": "Молдова", "BOL": "Боливия", "VEN": "Венесуэла",
    "TZA": "Танзания", "BRN": "Бруней", "COD": "ДР Конго", "COG": "Республика Конго", "PSE": "Палестина",
    "VAT": "Ватикан", "MKD": "Северная Македония", "CZE": "Чехия", "CIV": "Кот-д'Ивуар", "CPV": "Кабо-Верде",
    "BIH": "Босния и Герцеговина", "FSM": "Микронезия", "AIN": "Индивидуальные нейтральные атлеты",
    "HKG": "Гонконг", "ARE": "ОАЭ", "PRI": "Пуэрто-Рико", "MAC": "Макао",
}
# IOC codes (as in FIG tables) that differ from ISO alpha-3 / ISO 3166-3
IOC_TO_ID = {
    "GER": "DEU", "BUL": "BGR", "GRE": "GRC", "SLO": "SVN", "SUI": "CHE", "NED": "NLD", "DEN": "DNK",
    "POR": "PRT", "CRO": "HRV", "LAT": "LVA", "INA": "IDN", "RSA": "ZAF", "UAE": "ARE", "TPE": "TWN",
    "URS": "SUHH", "TCH": "CSHH", "GDR": "DDDE", "FRG": "DEU", "YUG": "YUCS", "MAS": "MYS", "SRI": "LKA",
    "CHI": "CHL", "URU": "URY", "PUR": "PRI", "HKG": "HKG", "KOS": "XKX",
    # step 24 (continental championships): IOC codes of Africa, Asia, the Americas and Oceania that differ from ISO
    "ANG": "AGO", "ALG": "DZA", "NGR": "NGA", "ZIM": "ZWE", "MRI": "MUS", "MAD": "MDG", "TAN": "TZA", "ZAM": "ZMB",
    "BOT": "BWA", "LBA": "LBY", "SUD": "SDN", "GAM": "GMB", "TOG": "TGO", "MAW": "MWI", "SEY": "SYC", "GEQ": "GNQ",
    "CGO": "COG", "CHA": "TCD", "NIG": "NER", "BUR": "BFA", "LES": "LSO", "KSA": "SAU", "KUW": "KWT", "PHI": "PHL",
    "VIE": "VNM", "MGL": "MNG", "IRI": "IRN", "NEP": "NPL", "BAN": "BGD", "SIN": "SGP", "OMA": "OMN", "BRN": "BHR",
    "MYA": "MMR", "CAM": "KHM", "LIB": "LBN", "PLE": "PSE", "GUA": "GTM", "CRC": "CRI", "HON": "HND", "ESA": "SLV",
    "PAR": "PRY", "ARU": "ABW", "ISV": "VIR", "BAH": "BHS", "BAR": "BRB", "TRI": "TTO", "ANT": "ATG", "HAI": "HTI",
    "CAY": "CYM", "BER": "BMU", "IVB": "VGB", "GRN": "GRD", "SKN": "KNA", "VIN": "VCT", "FIJ": "FJI", "SAM": "WSM",
    "TGA": "TON", "VAN": "VUT", "SOL": "SLB", "ASA": "ASM", "MON": "MCO",
}
# aliases that ISO does not know: (alias, country_id, note)
MANUAL_ALIASES = [
    ("West Germany", "DEU", "ISO 3166 has no separate entry for the FRG: Germany continues it"),
    ("Federal Republic of Germany", "DEU", ""),
    ("East Germany", "DDDE", ""),
    ("Soviet Union", "SUHH", ""),
    ("Socialist Federal Republic of Yugoslavia", "YUCS", ""),
    ("Yugoslavia", "YUCS", ""),
    ("Korea", "KOR", "appears in 2022-2025 tables, i.e. South Korea"),
    ("Chinese Taipei", "TWN", "name used by FIG/IOC"),
    ("Great Britain", "GBR", ""),
    ("Hong Kong", "HKG", ""),
    ("Russian Rhythmic Gymnastics Federation", "RUS", "label of Russian gymnasts in 2021"),
    ("Individual Neutral Athletes", "AIN", "not a country: neutral status of Russian/Belarusian athletes"),
]
# rows that are not ISO countries: (country_id, name, note)
OTHER_ENTITIES = [("AIN", "Individual Neutral Athletes", "IOC/FIG status, not a country; real nationality unknown")]


def normalize(text: str) -> str:
    """Spelling-insensitive form: no accents, case, brackets, leading 'the', punctuation."""
    s = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    return re.sub(r"^the ", "", s)


def short_name(country, country_id: str) -> str:
    if country_id in SHORT_NAMES:
        return SHORT_NAMES[country_id]
    common = getattr(country, "common_name", None)
    return common or country.name.split(",")[0].strip()


def _russian(domain: str):
    try:
        return gettext.translation(domain, pycountry.LOCALES_DIR, languages=["ru"]).gettext
    except OSError:
        return lambda text: text


def build_reference() -> tuple[list[dict], list[dict]]:
    countries, aliases = [], []
    ru_current, ru_former = _russian("iso3166-1"), _russian("iso3166-3")

    def add_aliases(country_id: str, values: list[tuple[str, str]]) -> None:
        for alias, source in values:
            if alias:
                aliases.append({"alias": alias, "country_id": country_id, "source": source})

    for c in pycountry.countries:
        cid = c.alpha_3
        name = short_name(c, cid)
        countries.append({"country_id": cid, "name": name, "name_ru": SHORT_NAMES_RU.get(cid) or ru_current(c.name),
                          "iso_name": c.name, "alpha2": c.alpha_2,
                          "alpha3": c.alpha_3, "alpha4": "", "status": "current", "valid_until": "", "note": ""})
        add_aliases(cid, [(c.name, "iso_name"), (getattr(c, "official_name", ""), "iso_official"),
                          (getattr(c, "common_name", ""), "iso_common"), (name, "short"), (c.alpha_3, "iso_alpha3")])
    for h in pycountry.historic_countries:
        cid = h.alpha_4
        name = short_name(h, cid)
        countries.append({"country_id": cid, "name": name, "name_ru": SHORT_NAMES_RU.get(cid) or ru_former(h.name),
                          "iso_name": h.name, "alpha2": "", "alpha3": h.alpha_3,
                          "alpha4": h.alpha_4, "status": "former",
                          "valid_until": getattr(h, "withdrawal_date", ""), "note": getattr(h, "comment", "") or ""})
        add_aliases(cid, [(h.name, "iso_name"), (name, "short"), (h.alpha_4, "iso_alpha4")])
    for cid, name, note in OTHER_ENTITIES:
        countries.append({"country_id": cid, "name": name, "name_ru": SHORT_NAMES_RU.get(cid, ""), "iso_name": "",
                          "alpha2": "", "alpha3": "", "alpha4": "", "status": "other", "valid_until": "", "note": note})
    for alias, cid, note in MANUAL_ALIASES:
        add_aliases(cid, [(alias, "manual")])
    for code, cid in IOC_TO_ID.items():
        add_aliases(cid, [(code, "ioc_code")])
    return countries, aliases


def _write(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


@dataclass
class Match:
    country_id: str
    name: str
    method: str  # code | exact | contained | fuzzy | none
    score: float

    @property
    def needs_review(self) -> bool:
        return self.method in {"contained", "fuzzy", "none"}


class CountryReference:
    def __init__(self, countries: list[dict], aliases: list[dict]) -> None:
        self.by_id = {c["country_id"]: c for c in countries}
        self.by_alpha3 = {c["alpha3"]: c["country_id"] for c in countries if c["status"] == "current"}
        self.alias: dict[str, str] = {}
        for a in aliases:
            if a["country_id"] in self.by_id:  # an alias of a code the reference lacks (Kosovo, XKX) is skipped
                self.alias.setdefault(normalize(a["alias"]), a["country_id"])
        # whole-word containment is only tried for names long enough not to hit by accident
        self._long = sorted((k for k in self.alias if len(k) >= 5), key=len, reverse=True)

    def _match(self, country_id: str, method: str, score: float) -> Match:
        return Match(country_id, self.by_id[country_id]["name"], method, score)

    def match(self, text: str) -> Match:
        raw = text.strip()
        key = normalize(raw)
        if not key:
            return Match("", "", "none", 0.0)
        if re.fullmatch(r"[A-Za-z]{3}", raw):
            code = IOC_TO_ID.get(raw.upper(), raw.upper())
            if code in self.by_id:
                return self._match(code, "code", 1.0)
            if code in self.by_alpha3:
                return self._match(self.by_alpha3[code], "code", 1.0)
        if key in self.alias:
            return self._match(self.alias[key], "exact", 1.0)
        for name in self._long:
            if re.search(rf"\b{re.escape(name)}\b", key):
                return self._match(self.alias[name], "contained", 0.9)
        close = get_close_matches(key, list(self.alias), n=1, cutoff=FUZZY_CUTOFF)
        if close:
            return self._match(self.alias[close[0]], "fuzzy", round(SequenceMatcher(None, key, close[0]).ratio(), 2))
        return Match("", "", "none", 0.0)


def write_reference(directory: Path = REFERENCE) -> tuple[list[dict], list[dict]]:
    countries, aliases = build_reference()
    _write(directory / "countries.csv", COUNTRY_FIELDS, countries)
    _write(directory / "country_aliases.csv", ALIAS_FIELDS, aliases)
    return countries, aliases


def load_reference(directory: Path = REFERENCE) -> CountryReference:
    if not (directory / "countries.csv").exists():
        write_reference(directory)
    read = lambda name: list(csv.DictReader((directory / name).open(encoding="utf-8-sig")))  # noqa: E731
    return CountryReference(read("countries.csv"), read("country_aliases.csv"))


def main() -> int:
    countries, aliases = write_reference()
    former = sum(c["status"] == "former" for c in countries)
    print(f"{len(countries)} countries ({former} former, ISO 3166-3), {len(aliases)} aliases -> {REFERENCE}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
