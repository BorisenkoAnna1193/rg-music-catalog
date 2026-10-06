"""Classical or not: a flag for every work (1 = classical, 0 = not), for the dashboard filter and the share-by-year chart.

"Classical" = the academic tradition: opera, ballet and concert music, old and 20th century (Tchaikovsky, Bizet, Orff,
Shostakovich, Shchedrin...). Not classical: pop, rock, jazz standards, tango (Piazzolla), film scores (Zimmer, Morricone),
crossover and folk. The flag belongs to the WORK, so it follows the composer, not the performer: Boléro stays classical
when a rock band plays it, a Michael Jackson song stays pop when two cellists play it.

Order of the evidence (the first that applies wins; `basis` says which):
  manual         data/manual/classical_overrides.csv (work_key, is_classical): the owner's decision
  composer       the composer of the work (owner's alias) or any name credited on its tracks is in
                 data/manual/classical_composers.csv
  composer_in_title  a composer at the start of a title ("Mendelssohn: Violin Concerto")
  title_keyword  a strong classical sign in a title ("Op. 28", "Symphony", "Piano Concerto", "Sonata", "Requiem", "Act III")
  default        none of the above: 0
A credited name matches when all tokens of one of the `match` variants occur in it ("adolphe adam" needs both words,
so a singer called Adam does not make a work classical).
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

from rg_music.works import _fold

COMPOSERS = Path("data/manual/classical_composers.csv")
OVERRIDES = Path("data/manual/classical_overrides.csv")
# strong signs only: bare "Concerto", "Rhapsody", "Prelude", "Nocturne", "Overture" are also pop titles
# ("Bohemian Rhapsody", "Concerto de Berlin", "Harlem Nocturne", "Rock Prelude")
FORM = re.compile(
    r"\b(op\.?\s*\d+|symphony|symphonic|(piano|violin|cello|flute|clarinet|guitar) concerto|concerto (no|for)\b|sonata|"
    r"requiem|act [ivx\d]+|caprice no|etude in|nocturne (in|no)|prelude (in|to act)|fantaisie-impromptu)",
    re.I,
)
ENSEMBLE = {"orchestra", "orchestre", "orquesta", "ensemble", "quartet", "quintet", "trio", "band", "choir", "chorus",
            "philharmonic", "philharmonia", "symphonic", "sinfonietta", "cast"}


def load_composers(path: Path = COMPOSERS) -> list[tuple[str, list[set[str]]]]:
    out = []
    if path.exists():
        for r in csv.DictReader(path.open(encoding="utf-8-sig")):
            out.append((r["name"], [set(v.split()) for v in r["match"].split("|") if v.strip()]))
    return out


def load_overrides(path: Path = OVERRIDES) -> dict[str, int]:
    if not path.exists():
        return {}
    return {r["work_key"]: int(r["is_classical"]) for r in csv.DictReader(path.open(encoding="utf-8-sig"))}


def composer_of(credit: str, composers: list[tuple[str, list[set[str]]]]) -> str:
    """The classical composer named in a credit ('' if none).

    A credit is split into names; a name that is an ensemble ("Johann Strauss Orchestra") is skipped: it is a
    performer named after a composer, not the composer.
    """
    for piece in re.split(r",|&|/|;| and ", credit):
        tokens = set(re.findall(r"\w+", _fold(piece)))
        if tokens & ENSEMBLE:
            continue
        for name, variants in composers:
            if any(v <= tokens for v in variants):
                return name
    return ""


def composer_in_title(title: str, composers: list[tuple[str, list[set[str]]]]) -> str:
    """A composer named at the start of a title: "Mendelssohn: Violin Concerto", "Glinka nocturne in F minor"."""
    head = re.findall(r"\w+", _fold(title))[:2]
    for name, variants in composers:
        if any(v <= set(head) for v in variants):
            return name
    return ""


def classify(work_key: str, composer: str, credits: list[str], titles: list[str],
             composers: list[tuple[str, list[set[str]]]], overrides: dict[str, int]) -> tuple[int, str, str]:
    """-> (is_classical, basis, composer name that made it classical)."""
    if work_key in overrides:
        return overrides[work_key], "manual", ""
    for credit in [composer, *credits]:
        if credit and (name := composer_of(credit, composers)):
            return 1, "composer", name
    for t in titles:
        if name := composer_in_title(t, composers):
            return 1, "composer_in_title", name
    if any(FORM.search(t) for t in titles):
        return 1, "title_keyword", ""
    return 0, "default", ""
