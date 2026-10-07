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
    python -m rg_music.works            first pass -> data/interim/work_candidates.csv (by title only)
    python -m rg_music.works --resolve  second pass -> track_works.csv, works.csv, versions.csv, work_splits.csv,
                                        work_merge_review.csv
Reads  data/interim/tracks.csv, routines_parsed.csv and, for the second pass, the owner's rules
       data/manual/work_aliases.csv (title_key, artist_contains -> work, excerpt, composer)

Second pass, in this order: the owner's aliases (e.g. every "O Fortuna" by Orff is "Carmina Burana: O Fortuna");
"Work: Excerpt" titles whose first part is the title of another track; "(from Work)" when that work is a track of
its own; spelling variants of one title
(0.95+ similar, same numbers, long enough); otherwise the title itself is the work.

Then (owner, 2026-10-07) one title with credits that share no name is split into DIFFERENT works until there is
evidence that it is one song: "Storm" by Otyken and "The Storm" by Havasi are two works. Evidence: an owner alias
(never split), one classical composer credited in the group and a title that is not generic ("Für Elise" by Hidden
Citizens stays Beethoven's; "Requiem", "Nocturne", "Ave Maria" are split), MusicBrainz: split groups that
python -m rg_music.mb_works linked to one MusicBrainz work are joined again (data/interim/work_mb_links.csv; the owner
can refuse a join in data/manual/work_mb_rejects.csv, column work_key). Tracks without a credit
stay with the title when it has one credited group, otherwise they form "<title> ~ no credit".
A version = work + performer as credited (the composer of the work is not a performer: "by Maurice Ravel" alone is
an unknown recording); spellings of one performer ("Beyoncé"/"Beyonce") are one version.
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




# ---------------------------------------------------------------- second pass: works, excerpts, spelling variants
ALIASES = Path("data/manual/work_aliases.csv")
AUTO_RATIO = 0.95  # spelling variants merged automatically (with the guards in fuzzy_groups)
REVIEW_RATIO = 0.88


def load_aliases(path: Path = ALIASES) -> list[dict]:
    """Owner's rules: title_key (+ optional artist_contains) -> work, excerpt, composer (+ optional work_key).

    Rows with an artist filter come first, in file order: put "Shchedrin" before "Bizet" when a credit names both.
    work_key is only needed when two different works have the same title ("Carmen" by Bizet and by Stromae).
    """
    if not path.exists():
        return []
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig")))
    return sorted(rows, key=lambda r: not r["artist_contains"])


def find_alias(key: str, artist: str, aliases: list[dict]) -> dict | None:
    for a in aliases:
        if a["title_key"] == key and (not a["artist_contains"] or _fold(a["artist_contains"]) in _fold(artist)):
            return a
    return None


class _Union:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        self.parent[self.find(a)] = self.find(b)


def fuzzy_groups(info: dict[str, dict]) -> tuple[dict[str, str], list[dict]]:
    """Merge spelling variants of one title. info: key -> {"gymnasts": n, "tracks": n, "artists": [..]}.

    Auto-merge when the keys are 0.95+ similar, carry the same numbers ("No. 1" is not "No. 2"), are at
    least 10 characters long and do not differ only by a plural s (short titles). Other near pairs are returned
    for review. -> (key -> representative key, review rows)
    """
    from difflib import SequenceMatcher

    blocks: dict[str, set[str]] = defaultdict(set)
    for k in info:
        for tok in k.split()[:2]:
            blocks[tok[:4]].add(k)
    uf, review, seen = _Union(), [], set()
    for members in blocks.values():
        for a, b in combinations(sorted(members), 2):
            if (a, b) in seen:
                continue
            seen.add((a, b))
            m = SequenceMatcher(None, a, b)
            if min(m.real_quick_ratio(), m.quick_ratio()) < REVIEW_RATIO or (ratio := m.ratio()) < REVIEW_RATIO:
                continue
            same_numbers = re.findall(r"\d+", a) == re.findall(r"\d+", b)
            short = min(a, b, key=len)
            plural_only = a + "s" == b or b + "s" == a  # "Main Title"/"Main Titles", "Queen"/"Queens": usually different
            ta, tb = set().union(*map(name_tokens, info[a]["artists"] or [""])), set().union(*map(name_tokens, info[b]["artists"] or [""]))
            # different performers of one song are normal (the key is the work), so credits do not block a merge;
            # short and generic titles do: only long, distinctive titles are merged without a human
            if ratio >= AUTO_RATIO and same_numbers and len(short) >= 10 and not (plural_only and len(short) < 14):
                uf.union(a, b)
            else:
                review.append({"title_a": a, "title_b": b, "similarity": round(ratio, 2),
                               "gymnasts_a": info[a]["gymnasts"], "gymnasts_b": info[b]["gymnasts"],
                               "artists_a": " | ".join(info[a]["artists"][:2]), "artists_b": " | ".join(info[b]["artists"][:2]),
                               "why_not_merged": "different numbers" if not same_numbers else
                               "short or generic title" if len(short) < 10 or plural_only else f"similarity below {AUTO_RATIO}"})
    best: dict[str, str] = {}
    for k in info:  # representative: the most used spelling
        root = uf.find(k)
        if root not in best or (info[k]["gymnasts"], info[k]["tracks"], k) > (info[best[root]]["gymnasts"], info[best[root]]["tracks"], best[root]):
            best[root] = k
    return {k: best[uf.find(k)] for k in info}, sorted(review, key=lambda r: -r["similarity"])


def _credit_names(tracks: list[dict]) -> set[str]:
    """Every credited name in the data, as keys, plus the surnames of multi-word names."""
    names: set[str] = set()
    for t in tracks:
        for piece in re.split(r",|&|/|;| and ", t["artist"]):
            k = title_key(piece)
            if k:
                names.add(k)
                if " " in k:
                    names.add(k.split()[-1])
    return names


# a classical composer in a group does not hold these titles together: they name a form, not one work
GENERIC_TITLES = {
    "adagio", "ave maria", "ballade", "barcarolle", "berceuse", "concerto", "elegy", "etude", "fantasia", "fantasy",
    "finale", "intermezzo", "introduction", "lullaby", "main theme", "main title", "march", "nocturne", "overture",
    "prelude", "requiem", "rhapsody", "romance", "serenade", "sonata", "suite", "tango", "theme", "valse", "waltz",
}
_CREDIT_SPLIT = r",|&|/|;| and "


def _credit_groups(rows: list[dict]) -> list[list[dict]]:
    """Rows whose credits share a name, or are one name spelled apart ("33Tours"/"33 Tours"), form one group."""
    uf = _Union()
    for i in range(len(rows)):
        uf.find(str(i))
        for j in range(i):
            a, b = rows[i]["artist"], rows[j]["artist"]
            if name_tokens(a) & name_tokens(b) or performer_key(a) == performer_key(b):
                uf.union(str(i), str(j))
    groups: dict[str, list[dict]] = defaultdict(list)
    for i, r in enumerate(rows):
        groups[uf.find(str(i))].append(r)
    return list(groups.values())


MB_LINKS = INTERIM / "work_mb_links.csv"
MB_REJECTS = Path("data/manual/work_mb_rejects.csv")


def load_mb_links(path: Path = MB_LINKS, rejects: Path = MB_REJECTS) -> dict[str, str]:
    """split work_key -> MusicBrainz work id, without the joins the owner refused."""
    if not path.exists():
        return {}
    refused = {r["work_key"] for r in csv.DictReader(rejects.open(encoding="utf-8-sig"))} if rejects.exists() else set()
    return {r["work_key"]: r["mb_work_id"] for r in csv.DictReader(path.open(encoding="utf-8-sig"))
            if r["mb_work_id"] and r["work_key"] not in refused}


def _join_by_musicbrainz(key: str, rs: list[dict], mb_links: dict[str, str]) -> None:
    """Split groups of one title that are one MusicBrainz work become one work again: the plain title when that is
    the only join of the title, else "<title> ~ <credit of its biggest group>"."""
    sizes = Counter(r["work_key"] for r in rs)
    per_work: dict[str, list[str]] = defaultdict(list)
    for k in sizes:
        if k in mb_links:
            per_work[mb_links[k]].append(k)
    joins = [ks for ks in per_work.values() if len(ks) > 1]
    for ks in joins:
        target = key if len(joins) == 1 else max(ks, key=lambda k: (sizes[k], k))
        for r in rs:
            if r["work_key"] in ks:
                r.update(work_key=target, same_title="joined_by_musicbrainz")


def split_by_credit(rows: list[dict], composers: list, mb_links: dict[str, str] | None = None) -> list[dict]:
    """Same work_key, credits with no name in common -> separate work keys "<key> ~ <main credit>"; then the groups
    MusicBrainz shows to be one work are joined again."""
    from rg_music.classical import composer_of  # lazy: classical imports this module

    by_key: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        r.update(title_cluster=r["work_key"], same_title="", split_key="")
        if r["method"] != "alias":  # the owner has decided these
            by_key[r["work_key"]].append(r)
    for key, rs in by_key.items():
        credited = [r for r in rs if name_tokens(r["artist"])]
        groups = _credit_groups(credited)
        if len(groups) <= 1:
            continue
        named = {composer_of(r["artist"], composers) for r in credited} - {""}
        if len(named) == 1 and key not in GENERIC_TITLES:
            for r in rs:
                r["same_title"] = "kept_classical_title"
            continue
        for g in groups:
            main = sorted(Counter(r["artist"] for r in g).items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
            for r in g:
                r.update(work_key=f"{key} ~ {title_key(main)}", same_title="split_by_credit")
        ids = {id(r) for r in credited}
        for r in rs:
            if id(r) not in ids:
                r.update(work_key=f"{key} ~ no credit", same_title="split_by_credit")
            r["split_key"] = r["work_key"]  # kept after a join: mb_works checks the groups by this key
        _join_by_musicbrainz(key, rs, mb_links or {})
    return rows


def performer_of(credit: str, work_composer: str, composers: list) -> str:
    """The credit without the composer of the work: '' when only the composer is named (recording unknown)."""
    from rg_music.classical import composer_of

    pieces = [p.strip() for p in re.split(_CREDIT_SPLIT, credit) if p.strip()]
    own = name_tokens(work_composer)
    keep = [p for p in pieces if not composer_of(p, composers) and not (own and name_tokens(p) & own)]
    return credit.strip() if len(keep) == len(pieces) else ", ".join(keep)


def performer_key(performer: str) -> str:
    """'The Brian Setzer Orchestra' = 'Brian Setzer Orchestra', 'Beyoncé' = 'Beyonce', '2 Cellos' = '2Cellos'."""
    s = re.sub(r"^the\s+", "", _fold(performer).strip())
    return re.sub(r"[^\w]+", "", s) or "unknown"


def version_type(title: str, performer: str) -> str:
    """original / cover need the original performer (MusicBrainz, later); here only what the text says."""
    if not performer:
        return "unknown"
    if re.search(r"\bremix", title, re.I):
        return "remix"
    if re.search(r"\bcast\b|broadway", performer, re.I):
        return "cast"
    return "unknown"


def resolve_works(tracks: list[dict], routines: dict[str, dict], aliases: list[dict],
                  mb_links: dict[str, str] | None = None) -> tuple[list[dict], list[dict], list[dict]]:
    """-> (track_works, works, merge_review). Order of rules: owner aliases, "Work: Excerpt", spelling variants, title,
    then one title with unrelated credits is split. Every track_works row also gets its version (performer)."""
    usable = [t for t in tracks if title_key(t["title"]) and t["routine_id"] in routines]
    keys = {title_key(t["title"]) for t in usable}

    info: dict[str, dict] = {}
    for k in keys:
        ts = [t for t in usable if title_key(t["title"]) == k]
        info[k] = {"gymnasts": len({routines[t["routine_id"]]["gymnast_page"] for t in ts}), "tracks": len(ts),
                   "artists": [a for a, _ in Counter(t["artist"] for t in ts if t["artist"]).most_common()]}
    representative, review = fuzzy_groups(info)
    names = _credit_names(usable)

    rows = []
    for t in usable:
        key = title_key(t["title"])
        alias = find_alias(key, t["artist"], aliases)
        prefix = t["title"].split(":", 1)[0] if ":" in t["title"] else ""
        if alias:
            row = dict(work_key=alias.get("work_key") or title_key(alias["work"]), work=alias["work"], excerpt=alias["excerpt"],
                       composer=alias["composer"], method="alias")
        elif prefix and len(title_key(prefix)) >= 3 and title_key(prefix) in names and title_key(t["title"].split(":", 1)[1]):
            # "Chopin: Fantasie" - the part before the colon is the composer, not the work
            rest = t["title"].split(":", 1)[1].strip()
            row = dict(work_key=title_key(rest), work=rest, excerpt="", composer=prefix.strip(), method="composer_prefix")
        elif (prefix and len(title_key(prefix)) >= 4 and title_key(prefix) != key and title_key(prefix) in keys
              and (not info[title_key(prefix)]["artists"] or not t["artist"]
                   or name_tokens(t["artist"]) & set().union(*map(name_tokens, info[title_key(prefix)]["artists"])))):
            # "Carmen: Habanera" next to a track titled "Carmen" with a credit in common
            row = dict(work_key=representative[title_key(prefix)], work=prefix.strip(), excerpt=t["title"].split(":", 1)[1].strip(),
                       composer="", method="colon_prefix")
        elif (parent := title_key(t.get("work", ""))) and parent != key and parent in keys and (
                not info[parent]["artists"] or not t["artist"]
                or name_tokens(t["artist"]) & set().union(*map(name_tokens, info[parent]["artists"]))):
            # "At the Circus (from Spartacus)": the cell names the work, and the work exists as a track of its own
            row = dict(work_key=representative[parent], work=t["work"].strip(), excerpt=t["title"], composer="", method="from_work")
        elif representative[key] != key:
            row = dict(work_key=representative[key], work="", excerpt="", composer="", method="spelling_variant")
        else:
            row = dict(work_key=key, work="", excerpt="", composer="", method="title")
        rows.append({"routine_id": t["routine_id"], "track_no": t["track_no"], "title": t["title"], "artist": t["artist"], **row})

    from rg_music.classical import classify, load_composers, load_overrides  # lazy: classical imports this module

    classical_composers, classical_overrides = load_composers(), load_overrides()
    rows = split_by_credit(rows, classical_composers, mb_links)
    by_key: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_key[r["work_key"]].append(r)
    works = []
    for key, rs in by_key.items():
        titles = Counter(r["work"] or r["title"] for r in rs)
        shown = next((r["work"] for r in rs if r["method"] == "alias"), "") or titles.most_common(1)[0][0]
        for r in rs:
            r["work"] = shown
        rr = [routines[r["routine_id"]] for r in rs]
        years = [int(x["year"]) for x in rr if str(x["year"]).isdigit()]
        artists = Counter(r["artist"] for r in rs if r["artist"])
        works.append({
            "work_key": key, "work": shown, "composer": next((r["composer"] for r in rs if r["composer"]), ""),
            "n_gymnasts": len({x["gymnast_page"] for x in rr}), "n_routines": len({r["routine_id"] for r in rs}),
            "n_tracks": len(rs), "first_year": min(years, default=""), "last_year": max(years, default=""),
            "excerpts": " | ".join(f"{e} ({n})" for e, n in Counter(r["excerpt"] for r in rs if r["excerpt"]).most_common(5)),
            "title_variants": len({r["title"] for r in rs}), "artists": " | ".join(f"{a} ({n})" for a, n in artists.most_common(4)),
            "artist_check": artist_check(list(artists)),
        })
        composer = works[-1]["composer"]
        is_classical, basis, who = classify(key, composer, list(artists), [r["title"] for r in rs] + [shown],
                                            classical_composers, classical_overrides)
        works[-1].update(is_classical=is_classical, classical_basis=basis, classical_composer=who or composer if is_classical else "")
    for w in works:
        rs = by_key[w["work_key"]]
        for r in rs:
            r["performer"] = performer_of(r["artist"], w["composer"] or w["classical_composer"], classical_composers)
            r["version_key"] = f"{w['work_key']} | {performer_key(r['performer'])}"
            r["version_type"] = version_type(r["title"], r["performer"])
        w["n_versions"] = len({r["version_key"] for r in rs})
    works.sort(key=lambda r: (-r["n_gymnasts"], -r["n_routines"], r["work_key"]))
    return rows, works, review


def build_versions(rows: list[dict], routines: dict[str, dict]) -> list[dict]:
    by: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by[r["version_key"]].append(r)
    out = []
    for key, rs in by.items():
        rr = [routines[r["routine_id"]] for r in rs]
        years = [int(x["year"]) for x in rr if str(x["year"]).isdigit()]
        used = sorted({(x["gymnast_page"], str(x["year"])) for x in rr})
        out.append({
            "version_key": key, "work_key": rs[0]["work_key"], "work": rs[0]["work"],
            "performer": Counter(r["performer"] for r in rs).most_common(1)[0][0],
            "version_type": Counter(r["version_type"] for r in rs).most_common(1)[0][0],
            "n_gymnasts": len({x["gymnast_page"] for x in rr}), "n_routines": len({r["routine_id"] for r in rs}),
            "first_year": min(years, default=""), "last_year": max(years, default=""),
            "used_by": " | ".join(f"{g} {y}" for g, y in used[:6]) + (" | ..." if len(used) > 6 else ""),
        })
    return sorted(out, key=lambda v: (v["work_key"], -v["n_gymnasts"], v["version_key"]))


def build_splits(rows: list[dict], routines: dict[str, dict]) -> list[dict]:
    """One row per title whose credits disagree: split into works, or kept together as one classical work."""
    by: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r["same_title"]:
            by[r["title_cluster"]].append(r)
    out = []
    for key, rs in by.items():
        parts: dict[str, list[dict]] = defaultdict(list)
        for r in rs:
            parts[r["work_key"] if r["same_title"] != "kept_classical_title" else r["performer"] or "(composer only)"].append(r)
        out.append({
            "title_key": key, "decision": next((d for d in ("kept_classical_title", "joined_by_musicbrainz")
                                                if any(r["same_title"] == d for r in rs)), "split_by_credit"),
            "n_gymnasts": len({routines[r["routine_id"]]["gymnast_page"] for r in rs}), "n_parts": len(parts),
            "parts": " | ".join(f"{p} ({len({routines[r['routine_id']]['gymnast_page'] for r in prs})})"
                                for p, prs in sorted(parts.items(), key=lambda kv: -len(kv[1]))),
        })
    return sorted(out, key=lambda r: (r["decision"], -r["n_gymnasts"], r["title_key"]))


TRACK_WORK_FIELDS = ["routine_id", "track_no", "title", "artist", "work_key", "work", "excerpt", "composer", "method",
                     "title_cluster", "same_title", "split_key", "performer", "version_key", "version_type"]
WORK_FIELDS = ["work_key", "work", "composer", "n_gymnasts", "n_routines", "n_tracks", "n_versions", "first_year",
               "last_year", "excerpts", "title_variants", "artists", "artist_check", "is_classical", "classical_basis",
               "classical_composer"]
VERSION_FIELDS = ["version_key", "work_key", "work", "performer", "version_type", "n_gymnasts", "n_routines",
                  "first_year", "last_year", "used_by"]
SPLIT_FIELDS = ["title_key", "decision", "n_gymnasts", "n_parts", "parts"]
REVIEW_FIELDS = ["title_a", "title_b", "similarity", "gymnasts_a", "gymnasts_b", "artists_a", "artists_b", "why_not_merged"]


def main_resolve() -> int:
    read = lambda name: list(csv.DictReader((INTERIM / name).open(encoding="utf-8")))  # noqa: E731
    tracks, routines = read("tracks.csv"), {r["routine_id"]: r for r in read("routines_parsed.csv")}
    track_works, works, review = resolve_works(tracks, routines, load_aliases(), load_mb_links())
    versions, splits = build_versions(track_works, routines), build_splits(track_works, routines)
    for name, fields, data in (("track_works.csv", TRACK_WORK_FIELDS, track_works), ("works.csv", WORK_FIELDS, works),
                               ("versions.csv", VERSION_FIELDS, versions), ("work_splits.csv", SPLIT_FIELDS, splits),
                               ("work_merge_review.csv", REVIEW_FIELDS, review)):
        with (INTERIM / name).open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(data)
    methods = Counter(t["method"] for t in track_works)
    print(f"{len(works)} works (first pass: 2489), used by 2+ gymnasts: {sum(w['n_gymnasts'] > 1 for w in works)}; "
          f"how tracks were assigned: {dict(methods)}; pairs left for review: {len(review)}")
    decisions = Counter(s["decision"] for s in splits)
    print(f"{len(versions)} versions; titles with unrelated credits: {dict(decisions)} "
          f"({sum(s['n_parts'] for s in splits if s['decision'] != 'kept_classical_title')} works after split and join)")
    return 0


if __name__ == "__main__":
    sys.exit(main_resolve() if "--resolve" in sys.argv else main())
