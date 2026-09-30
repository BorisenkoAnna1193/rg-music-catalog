"""Cross-check the two music sources found on the same page.

For every routine in a competition table (e.g. the Olympic results) we look
for the same gymnast + apparatus in the routine table and compare the music.

Usage:
    python -m rg_music.crosscheck
Output:
    data/interim/crosscheck.csv
"""

from __future__ import annotations

import csv
import re
import sys
import unicodedata
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

INTERIM = Path("data/interim")
FUZZY_OK = 0.85


def base_apparatus(app: str) -> str:
    """'Ball (second)' -> 'ball', 'Clubs at LA Lights' -> 'clubs', 'Ribbons' -> 'ribbon'."""
    word = re.split(r"[\s(\-]", app.strip().lower(), maxsplit=1)[0]
    return word.rstrip("s") if word.endswith("s") and word != "clubs" else word


def norm_music(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = text.lower().replace("&", " and ")
    text = re.sub(r"[\"'“”‘’«»]", "", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, norm_music(a), norm_music(b)).ratio()


def main() -> int:
    routines = list(csv.DictReader((INTERIM / "routines_raw.csv").open(encoding="utf-8")))
    comps = [
        r for r in csv.DictReader((INTERIM / "competitions_raw.csv").open(encoding="utf-8"))
        if r["music"] and base_apparatus(r["apparatus"]) != "all"
    ]

    index: dict[tuple, list[dict]] = {}
    for r in routines:
        if r["music"]:
            key = (r["gymnast_page"], base_apparatus(r["apparatus"]))
            index.setdefault(key, []).append(r)

    out = []
    for c in comps:
        candidates = index.get((c["gymnast_page"], base_apparatus(c["apparatus"])), [])
        year = int(c["year"])
        best, best_score = None, 0.0
        for r in candidates:
            score = similarity(c["music"], r["music"])
            # prefer the same season on ties
            if score > best_score or (score == best_score and best and r["year"] == c["year"]):
                best, best_score = r, score

        if best is None:
            status = "no_routine_for_apparatus"
        elif best_score < FUZZY_OK:
            status = "music_differs"
        elif best["year"] == c["year"]:
            status = "match" if best_score == 1.0 else "match_fuzzy"
        else:
            status = f"match_but_year_{'+' if int(best['year']) > year else ''}{int(best['year']) - year}"

        out.append({
            "gymnast_page": c["gymnast_page"],
            "competition": c["competition"],
            "year": c["year"],
            "apparatus": c["apparatus"],
            "competition_music": c["music"],
            "routine_year": best["year"] if best else "",
            "routine_apparatus": best["apparatus"] if best else "",
            "routine_music": best["music"] if best else "",
            "similarity": f"{best_score:.2f}",
            "status": status,
        })

    path = INTERIM / "crosscheck.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)

    print(f"{len(out)} competition routines checked -> {path}")
    for status, n in Counter(o["status"] for o in out).most_common():
        print(f"  {status:28} {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
