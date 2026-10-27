"""Official World Gymnastics spelling for every gymnast of the list: proposals for the owner (step 24).

Owner (2026-10-20, 2026-10-26): when a name differs, the official World Gymnastics (formerly FIG) spelling wins, in the
word order of Wikipedia. World Gymnastics is used for names only: nobody is added from its database.

The athlete search of gymnastics.sport is backed by a public JSON endpoint; one request returns every rhythmic
biography (about 11,000: id, preferred first and last name, country code, status; no birth date). It is cached in
data/raw/wg/bios_rg.json (git-ignored; --refresh downloads it again). robots.txt allows everything.

Only a real difference in letters is proposed: World Gymnastics mostly drops accents ('Lewinska' for 'Lewińska') and
splits hyphenated Korean names ('Yeon Jae Son'), so a name that differs only in accents, case, hyphens or word order
keeps its Wikipedia spelling.

A gymnast matches a biography when the name key (worlds.name_key: word order, accents and common transliterations
ignored) is the same and the country is the same; a key that fits several biographies, or only one in another country,
is shown but not proposed.

Usage:
    python -m rg_music.wg_names [--refresh]
Reads  data/interim/wc_gymnasts_final.csv
Writes data/interim/wg_name_proposals.csv  one row per gymnast: current name, World Gymnastics id and name, the
                                           proposed name, how it matched, change yes/no
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import requests

from .countries import load_reference
from .fig_names import normalize_fig_name
from .name_decisions import wiki_order
from .worlds import _plain, name_key

API = "https://www.gymnastics.sport/api/athletes.php?function=searchBios&discipline=RG"
CACHE = Path("data/raw/wg/bios_rg.json")
UA = "rg-music-catalog/0.1 (non-commercial fan catalogue; github.com/BorisenkoAnna1193/rg-music-catalog)"
DECISIONS = Path("data/manual/wg_name_decisions.csv")
FIELDS = ["gymnast_key", "canonical_name", "proposed_name", "change", "match", "wg_id", "wg_name", "wg_country", "wg_status",
          "country_id", "years", "events", "wiki_page", "name_source", "other_candidates", "decision", "owner_note"]


def load_bios(refresh: bool = False) -> list[dict]:
    if refresh or not CACHE.exists():
        r = requests.get(API, headers={"User-Agent": UA}, timeout=120)
        r.raise_for_status()
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(r.text, encoding="utf-8")
    return json.loads(CACHE.read_text(encoding="utf-8"))


def wg_display(b: dict) -> str:
    """'AVERINA' + 'Dina' -> 'Dina Averina' (the surname is written in capitals by World Gymnastics)."""
    return normalize_fig_name(f"{b['preferredlastname'].upper()} {b['preferredfirstname']}")


def letters(name: str) -> list[str]:
    """Words without accents, case, hyphens, apostrophes and order: 'Son Yeon-jae' == 'SON Yeon Jae'."""
    return sorted(re.sub(r"[^a-z ]", " ", _plain(name)).split())


def propose(gymnasts: list[dict], bios: list[dict]) -> list[dict]:
    ref = load_reference()
    by_key: dict[str, list[dict]] = defaultdict(list)
    for b in bios:
        by_key[name_key(f"{b['preferredfirstname']} {b['preferredlastname']}")].append(b)
    country_of = {code: ref.match(code).country_id or code for code in dict.fromkeys(b["code"] for b in bios)}
    out = []
    for g in gymnasts:
        keys = {name_key(g["canonical_name"])} | {name_key(s) for s in g["spellings"].split(" | ") if s}
        cands = {b["id"]: b for k in keys for b in by_key.get(k, [])}.values()
        same = [b for b in cands if country_of[b["code"]] == g["country_id"]]
        row = {f: "" for f in FIELDS} | {k: g[k] for k in ("canonical_name", "country_id", "years", "events",
                                                           "wiki_page", "name_source")}
        row["gymnast_key"] = g["gymnast_keys"].split(" | ")[0]
        if len(same) == 1:
            b = same[0]
            row |= {"match": "name+country", "wg_id": b["id"], "wg_name": wg_display(b), "wg_country": b["code"],
                    "wg_status": b["gymnaststatus"]}
            # World Gymnastics mostly drops accents and splits hyphenated names: a name that differs only so keeps the
            # Wikipedia spelling; a real difference in letters is proposed in the Wikipedia word order
            row["proposed_name"] = g["canonical_name"] if letters(row["wg_name"]) == letters(g["canonical_name"]) \
                else wiki_order(row["wg_name"], g["canonical_name"])
        else:
            row["match"] = "ambiguous" if len(same) > 1 else ("other_country" if cands else "not_found")
            row["proposed_name"] = g["canonical_name"]
        row["other_candidates"] = " | ".join(f"{wg_display(b)} ({b['code']}, {b['id']})" for b in cands
                                             if not (len(same) == 1 and b is same[0]))
        row["change"] = "yes" if row["proposed_name"] != g["canonical_name"] else ""
        out.append(row)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--refresh", action="store_true", help="download the World Gymnastics list again")
    ap.add_argument("--dir", type=Path, default=Path("data/interim"))
    args = ap.parse_args(argv)
    with (args.dir / "wc_gymnasts_final.csv").open(encoding="utf-8-sig") as f:
        gymnasts = list(csv.DictReader(f))
    rows = propose(gymnasts, load_bios(args.refresh))
    if DECISIONS.exists():  # the owner's earlier answers: a rejected spelling is shown with her decision, not proposed
        with DECISIONS.open(encoding="utf-8-sig") as f:
            decided = {(d["gymnast_key"], d["name_after"]): d for d in csv.DictReader(f)}
        for r in rows:
            if d := decided.get((r["gymnast_key"], r["proposed_name"])):
                r["decision"], r["owner_note"] = d["decision"], d["owner_note"]
                r["change"] = "yes" if d["decision"] == "accept" and r["proposed_name"] != r["canonical_name"] else ""
    rows.sort(key=lambda r: (r["change"] != "yes", r["match"], r["canonical_name"].lower()))
    with (args.dir / "wg_name_proposals.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    counts = Counter(r["match"] for r in rows)
    print(f"{len(rows)} gymnasts: {dict(counts)}; name would change for {sum(r['change'] == 'yes' for r in rows)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
