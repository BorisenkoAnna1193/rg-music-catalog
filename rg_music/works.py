"""First pass of music matching: candidate "works" (same title, check the authors).

Decided with the owner: "the same music" = the same work (not the same recording); a different excerpt of
one work is fine; the key is title + author/composer, not the title alone. The data do not say whether
a plain "by X" is the composer or one performer, so this pass groups by a normalised TITLE and reports,
for every group, whether the credited names agree:
    same_author       every pair of tracks shares a name (or a surname) - very likely one work
    different_authors some tracks share no name - one song performed by different artists, or different
                      songs with one title ("Hurt"); to be decided with MusicBrainz or by hand

Title normalisation ignores case, accents, "The", brackets ("(Remix)", "(from ...)") and trailing version
words (remix, instrumental, cover...). It works for any script (Cyrillic, Korean...).

Usage:
    python -m rg_music.works
Reads  data/interim/tracks.csv, routines_parsed.csv
Writes data/interim/work_candidates.csv   one row per candidate work, most popular first
"""

from __future__ import annotations

import csv
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

INTERIM = Path("data/interim")
FIELDS = ["work_key", "title", "artists", "n_gymnasts", "n_routines", "n_tracks", "first_year",
          "last_year", "n_artist_variants", "artist_check"]
_VERSION_WORDS = r"(?:remix(?:ed)?|instrumental|cover|version|edit|extended|mix|live|original|radio|club|dub)"
_NAME_STOP = {"and", "the", "feat", "ft", "with", "orchestra", "symphony", "philharmonic", "choir", "band",
              "quartet", "ensemble", "cast", "soundtrack", "ost", "from", "music"}


def _fold(text: str) -> str:
    """Case- and accent-insensitive, any script: 'Boléro' -> 'bolero', 'Двигаться' stays Cyrillic."""
    s = unicodedata.normalize("NFKD", text).casefold()
    # NFC again: accents are gone, but Hangul syllables must be put back together (NFKD splits them into jamo)
    return unicodedata.normalize("NFC", "".join(c for c in s if not unicodedata.combining(c)))


def title_key(title: str) -> str:
    s = _fold(re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", title))
    s = re.sub(r"[^\w]+", " ", s).strip()
    s = re.sub(rf"(?:\s+{_VERSION_WORDS})+$", "", s)
    s = re.sub(r"^(?:the|a|an)\s+", "", s)
    return s.strip()


def name_tokens(artist: str) -> set[str]:
    """Surname-sized words of the credited names, without generic words (and, orchestra...)."""
    return {t for t in re.findall(r"\w+", _fold(artist)) if len(t) >= 3 and t not in _NAME_STOP}


def artist_check(artists: list[str]) -> str:
    """same_author when every pair of non-empty credits shares a word; no_credit when none is given."""
    sets = [name_tokens(a) for a in artists if a]
    if not sets:
        return "no_credit"
    if len(sets) == 1:
        return "same_author"
    return "same_author" if all(a & b for a, b in combinations(sets, 2)) else "different_authors"


def build_candidates(tracks: list[dict], routines: dict[str, dict]) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for t in tracks:
        key = title_key(t["title"])
        if key and t["routine_id"] in routines:
            groups[key].append(t)

    rows = []
    for key, ts in groups.items():
        rs = [routines[t["routine_id"]] for t in ts]
        titles = Counter(t["title"] for t in ts)
        artists = Counter(t["artist"] for t in ts if t["artist"])
        distinct = list(artists)
        years = [int(r["year"]) for r in rs if str(r["year"]).isdigit()]
        rows.append({
            "work_key": key,
            "title": titles.most_common(1)[0][0],
            "artists": " | ".join(f"{a} ({n})" for a, n in artists.most_common(4)),
            "n_gymnasts": len({r["gymnast_page"] for r in rs}),
            "n_routines": len({t["routine_id"] for t in ts}),
            "n_tracks": len(ts),
            "first_year": min(years, default=""), "last_year": max(years, default=""),
            "n_artist_variants": len(distinct),
            "artist_check": artist_check(distinct),
        })
    return sorted(rows, key=lambda r: (-r["n_gymnasts"], -r["n_routines"], r["work_key"]))


def main() -> int:
    read = lambda name: list(csv.DictReader((INTERIM / name).open(encoding="utf-8")))  # noqa: E731
    tracks = read("tracks.csv")
    routines = {r["routine_id"]: r for r in read("routines_parsed.csv")}
    rows = build_candidates(tracks, routines)
    with (INTERIM / "work_candidates.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    checks = Counter(r["artist_check"] for r in rows)
    print(f"{len(rows)} candidate works from {sum(r['n_tracks'] for r in rows)} tracks; "
          f"used by 2+ gymnasts: {sum(r['n_gymnasts'] > 1 for r in rows)}; artist check: {dict(checks)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
