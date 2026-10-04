"""Apply the name hierarchy to the review sheet and build the final gymnast list.

Hierarchy for the canonical name (decided with the owner):
  1. FIG name (from wc_name_review_fig.csv), written "Given Surname" with the surname
     capitalised in the standard way (AVERINA -> Averina);
  2. no FIG entry but a Wikipedia article: the article title (without "(gymnast)");
  3. neither: the table spelling used most often, ties -> the latest year.

Two rows of the review sheet (a "possible_duplicate" group) are the same person when
  - their FIG names are equal, or
  - the names are identical up to word order/transliteration (a gymnast who competed for
    two countries or successor states), or
  - same country and the two never stand in the same results table (assumed, flagged).
They are different people when their FIG names differ, when both stand in the same table,
or when both country and spelling differ.
A gymnast who competed for two countries gets the country of the latest championship
(entries that are not countries, e.g. Individual Neutral Athletes, are skipped).

A decision the owner typed into wc_name_review_fig.csv (a row with `decision_basis` empty)
is never overwritten; rows filled by this script carry the reason in `decision_basis`.

Usage:
    python -m rg_music.name_decisions
Reads  data/interim/wc_name_review_fig.csv, wc_gymnasts.csv, wc_appearances.csv
Writes data/interim/wc_name_review_fig.csv (decision, canonical_name, decision_basis filled)
       data/interim/wc_gymnasts_final.csv  one row per person after merging
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

from .countries import load_reference
from .fig_names import normalize_fig_name
from .worlds import _plain, name_key

INTERIM = Path("data/interim")
FINAL_FIELDS = ["canonical_name", "name_ru", "name_source", "wiki_page", "fig_id", "country_id", "country", "country_ru",
                "country_history",
                "first_year", "last_year", "championships", "years", "spellings", "gymnast_keys"]


def _read(path: Path) -> list[dict]:
    return list(csv.DictReader(path.open(encoding="utf-8-sig")))


def parse_spellings(spellings: str) -> list[tuple[str, list[int]]]:
    """'Aliya Yusupova (2001,2005) | Aliya Yussupova (2003)' -> [(name, [years]), ...]"""
    out = []
    for part in spellings.split(" | "):
        m = re.match(r"^(.*) \(([\d,]+)\)$", part)
        out.append((m.group(1), [int(y) for y in m.group(2).split(",")]) if m else (part, []))
    return out


def best_name(rows: list[dict]) -> tuple[str, str]:
    """Canonical name for one person described by one or more review rows -> (name, source)."""
    for r in rows:
        if r["fig_name"]:
            return normalize_fig_name(r["fig_name"]), "fig"
    for r in rows:
        if r["wiki_page"]:
            return re.sub(r"\s*\(.*?\)$", "", r["wiki_page"]), "wikipedia"
    seen: dict[str, list[int]] = defaultdict(list)
    for r in rows:
        for name, years in parse_spellings(r["spellings"]):
            seen[name] += years
    name = max(seen, key=lambda n: (len(seen[n]), max(seen[n], default=0)))
    return name, "table"


def pair_decision(a: dict, b: dict, same_table: bool) -> tuple[str, str]:
    """('same' | 'different', reason) for two rows of one possible_duplicate group."""
    if a["fig_name"] and b["fig_name"]:
        if _plain(a["fig_name"]) == _plain(b["fig_name"]):
            return "same", "FIG names are equal"
        return "different", "FIG names differ"
    if same_table:
        return "different", "both stand in the same results table"
    if name_key(a["display_name"]) == name_key(b["display_name"]):
        return "same", "same name apart from word order/spelling (two countries)"
    if set(a["nations"].split(" | ")) & set(b["nations"].split(" | ")):
        return "same", "same country, never in the same table (assumed)"
    return "different", "different country and different spelling"


def latest_country(appearances: list[dict], not_countries: frozenset[str] = frozenset()) -> tuple[str, str, str]:
    """(country_id, short name of the latest championship's country, 'France 1983-1985 > Germany 1987').

    Countries come from the reference (country_id / country); the raw table text is the fallback.
    Entries that are not countries (e.g. Individual Neutral Athletes) stay in the history but are
    skipped when choosing the latest country, unless there is nothing else.
    """
    by_country: dict[tuple[str, str], list[int]] = {}
    for a in sorted(appearances, key=lambda x: int(x["year"])):
        name = a.get("country") or a.get("nation", "")
        if name:
            by_country.setdefault((a.get("country_id", ""), name), []).append(int(a["year"]))
    if not by_country:
        return "", "", ""
    history = " > ".join(f"{n} {y[0]}" if y[0] == y[-1] else f"{n} {y[0]}-{y[-1]}"
                         for (_, n), y in by_country.items())
    real = {k: v for k, v in by_country.items() if k[0] not in not_countries} or by_country
    cid, name = max(real, key=lambda k: max(real[k]))
    return cid, name, history


class Clusters:
    """Union-find over gymnast keys."""

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


def decide(review: list[dict], appearances: list[dict]) -> None:
    """Fill decision / canonical_name / decision_basis in place (manual cells are kept)."""
    tables = defaultdict(set)
    for a in appearances:
        tables[a["gymnast_key"]].add((a["year"], a["stage"]))

    groups: dict[str, list[dict]] = defaultdict(list)
    for r in review:
        r.setdefault("decision_basis", "")
        if r["reason"] == "possible_duplicate":
            groups[r["group"]].append(r)
        elif not r["decision"] and not r["decision_basis"]:
            name, source = best_name([r])
            r["decision"], r["canonical_name"] = "ok", name
            r["decision_basis"] = f"canonical name from {source}"

    for rows in groups.values():
        a, b = rows
        manual = next((r["decision"].lower() for r in rows if r["decision"] and not r["decision_basis"]), "")
        if manual:
            decision, reason = manual, "manual"
        else:
            decision, reason = pair_decision(a, b, bool(tables[a["gymnast_key"]] & tables[b["gymnast_key"]]))
        names = {r["canonical_name"] for r in rows if r["canonical_name"] and not r["decision_basis"]}
        for r in rows:
            if r["decision"] and not r["decision_basis"]:
                continue  # typed by the owner
            r["decision"] = decision
            if names:
                r["canonical_name"], source = sorted(names)[0], "manual"
            else:
                r["canonical_name"], source = best_name(rows if decision == "same" else [r])
            r["decision_basis"] = f"{reason}; canonical name from {source}"


def build_final(gymnasts: list[dict], review: list[dict], appearances: list[dict],
                not_countries: frozenset[str] = frozenset(), names_ru: dict[str, str] | None = None,
                countries_ru: dict[str, str] | None = None) -> list[dict]:
    """One row per person. names_ru: wiki_page -> Russian name; countries_ru: country_id -> Russian name
    (both optional; a missing Russian name stays empty so the UI can fall back to the Latin one)."""
    names_ru, countries_ru = names_ru or {}, countries_ru or {}
    clusters = Clusters()
    by_group: dict[str, list[dict]] = defaultdict(list)
    for r in review:
        if r["reason"] == "possible_duplicate":
            by_group[r["group"]].append(r)
    for rows in by_group.values():
        if rows[0]["decision"].lower() == "same":
            clusters.union(rows[0]["gymnast_key"], rows[1]["gymnast_key"])

    reviewed = {r["gymnast_key"]: r for r in review}
    members: dict[str, list[dict]] = defaultdict(list)
    for g in gymnasts:
        members[clusters.find(g["gymnast_key"])].append(g)
    apps: dict[str, list[dict]] = defaultdict(list)
    for a in appearances:
        apps[clusters.find(a["gymnast_key"])].append(a)

    out = []
    for root, gs in members.items():
        rows = [reviewed[g["gymnast_key"]] for g in gs if g["gymnast_key"] in reviewed]
        if rows and rows[0]["canonical_name"]:
            name, source = rows[0]["canonical_name"], rows[0]["decision_basis"].rsplit("from ", 1)[-1] or "manual"
        else:
            name, source = gs[0]["display_name"], "table"
        years = sorted({int(a["year"]) for a in apps[root]})
        country_id, country, history = latest_country(apps[root], not_countries)
        page = next((g["wiki_page"] for g in gs if g["wiki_page"]), "")
        out.append({
            "canonical_name": name, "name_ru": names_ru.get(page, ""), "name_source": source,
            "wiki_page": page,
            "fig_id": next((r["fig_id"] for r in rows if r.get("fig_id")), ""),
            "country_id": country_id, "country": country, "country_ru": countries_ru.get(country_id, ""),
            "country_history": history,
            "first_year": years[0], "last_year": years[-1], "championships": len(years),
            "years": ",".join(map(str, years)),
            "spellings": " | ".join(dict.fromkeys(a["name"] for a in apps[root])),
            "gymnast_keys": " | ".join(g["gymnast_key"] for g in gs),
        })
    return sorted(out, key=lambda r: r["canonical_name"].lower())


def _write(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dir", type=Path, default=INTERIM)
    args = ap.parse_args(argv)

    path = args.dir / "wc_name_review_fig.csv"
    review = _read(path)
    fields = list(review[0]) + (["decision_basis"] if "decision_basis" not in review[0] else [])
    appearances = _read(args.dir / "wc_appearances.csv")
    decide(review, appearances)
    _write(path, fields, review)

    ref = load_reference()
    not_countries = frozenset(cid for cid, c in ref.by_id.items() if c["status"] == "other")
    ru_file = args.dir / "gymnast_names_ru.csv"
    names_ru = {r["wiki_page"]: r["name_ru"] for r in _read(ru_file)} if ru_file.exists() else {}
    countries_ru = {cid: c["name_ru"] for cid, c in ref.by_id.items()}
    final = build_final(_read(args.dir / "wc_gymnasts.csv"), review, appearances, not_countries, names_ru, countries_ru)
    _write(args.dir / "wc_gymnasts_final.csv", FINAL_FIELDS, final)

    n_before = len(_read(args.dir / "wc_gymnasts.csv"))
    print(f"{n_before} gymnast rows -> {len(final)} people after merging same-person pairs")
    for r in review:
        if "assumed" in r["decision_basis"]:
            print("assumed:", r["group"], r["display_name"], "->", r["canonical_name"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
