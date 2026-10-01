"""Normalise apparatus spellings from the routine tables.

"Hoop (2nd)", "Clubs (Second)", "Ribbons", "Gala at EC Minsk",
"Gala-2 Ribbons (WCH Patras)" -> (apparatus, variant, context, notes).

variant is first/second/third or "" ; context is free text (event, gala type).
"""

from __future__ import annotations

import re
from typing import NamedTuple

BASE = {
    "hoop": "Hoop", "ball": "Ball", "clubs": "Clubs",
    "ribbon": "Ribbon", "ribbons": "Ribbon", "rope": "Rope", "gala": "Gala",
}
VARIANTS = {
    "first": "first", "1st": "first",
    "second": "second", "2nd": "second",
    "third": "third", "3rd": "third",
}
TYPOS = {"Autum": "Autumn"}

_HEAD = re.compile(r"^(hoop|ball|clubs|ribbons?|rope|gala)\b(.*)$", re.I)


class Apparatus(NamedTuple):
    apparatus: str
    variant: str
    context: str
    notes: list[str]


def normalize_apparatus(raw: str) -> Apparatus:
    m = _HEAD.match(raw.strip())
    if not m:
        return Apparatus("", "", raw.strip(), ["unknown_apparatus"])
    apparatus = BASE[m.group(1).lower()]
    rest = m.group(2)

    variant, context, notes = "", [], []
    for inner in re.findall(r"\(([^()]*)\)", rest):
        inner = inner.strip()
        if inner.lower() in VARIANTS:
            variant = VARIANTS[inner.lower()]
        else:
            context.append(inner)
    rest = re.sub(r"\([^()]*\)", " ", rest).strip()
    rest = re.sub(r"^(?:at\s+|-\s*)", "", rest, flags=re.I).strip()
    if rest:
        context.insert(0, rest)

    fixed = []
    for part in context:
        for typo, right in TYPOS.items():
            if re.search(rf"\b{typo}\b", part):
                part = re.sub(rf"\b{typo}\b", right, part)
                notes.append(f"typo_fixed_{typo}_to_{right}")
        fixed.append(part)
    return Apparatus(apparatus, variant, "; ".join(fixed), notes)
