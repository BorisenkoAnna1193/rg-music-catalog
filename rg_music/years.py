"""Years in the routine tables: "2023", but also seasons "2022/2023", "2017-18", "2010-2012"."""

from __future__ import annotations

import re

_PART = r"(?:19|20)\d{2}|\d{2}"
_YEARS = re.compile(rf"^({_PART})(?:\s*[-–/]\s*({_PART}))*$")


def parse_years(text: str) -> tuple[int, int] | None:
    """(first year, last year) of a year or a season; None when the text is not a year at all."""
    text = text.strip()
    if not _YEARS.match(text):
        return None
    tokens = re.findall(r"\d{4}|\d{2}", text)
    first = int(tokens[0])
    if first < 1900:
        return None
    years = [first]
    for t in tokens[1:]:
        y = int(t) if len(t) == 4 else int(str(first)[:2] + t)
        years.append(y + 100 if y < first else y)  # "1999-00" -> 2000
    return min(years), max(years)


def expand_years(text: str) -> list[int]:
    """Every year a season covers: "2022/2023" -> [2022, 2023]; "2010-2012" -> [2010, 2011, 2012]; [] if unreadable."""
    span = parse_years(text)
    return list(range(span[0], span[1] + 1)) if span else []
