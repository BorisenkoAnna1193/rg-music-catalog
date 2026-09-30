"""Normalise competition names and years in competition tables.

Olympic Games are named by their official brand ("Tokyo 2020"). The year is
the year the competition actually took place: Tokyo 2020 was held in 2021, so
a row dated 2020 is corrected to 2021 and flagged.
"""

from __future__ import annotations

import re

# location (lower-case) -> (official name, year actually held)
OLYMPICS = {
    "los angeles": ("Los Angeles 1984", "1984"),
    "seoul": ("Seoul 1988", "1988"),
    "barcelona": ("Barcelona 1992", "1992"),
    "atlanta": ("Atlanta 1996", "1996"),
    "sydney": ("Sydney 2000", "2000"),
    "athens": ("Athens 2004", "2004"),
    "beijing": ("Beijing 2008", "2008"),
    "london": ("London 2012", "2012"),
    "rio de janeiro": ("Rio 2016", "2016"),
    "rio": ("Rio 2016", "2016"),
    "tokyo": ("Tokyo 2020", "2021"),
    "paris": ("Paris 2024", "2024"),
}


def normalize_event(competition: str, location: str, year: str) -> tuple[str, str, list[str]]:
    """Return (competition, year, notes) for one competition-table row."""
    if not re.search(r"olympic", competition, re.I):
        return competition, year, []
    known = OLYMPICS.get(location.strip().lower())
    if known is None:
        return competition, year, ["unknown_olympics"]
    name, held = known
    notes = [f"year_corrected_{year}_to_{held}"] if year and year != held else []
    return name, held, notes
