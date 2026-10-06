"""Composer suggestions for the works used by 2+ gymnasts, from MusicBrainz (suggestions, never applied).

The credited name in our data is the composer for classical music ("by Maurice Ravel") but one performer
for a pop song ("Caruso by Lara Fabian"), so the composer has to come from outside. For every work (title) a
MusicBrainz work search is made and the candidates with exactly the same title are compared:

  high       a candidate whose composers share a name with a credit of this work in our data
  probable   exactly one candidate with that title (score 90+)
  ambiguous  several candidates with that title (e.g. "O Fortuna", "Carmen"): the first ones are listed
  none       nothing with that title

Works with a composer from the owner's aliases (data/manual/work_aliases.csv) are skipped.
MusicBrainz asks for at most 1 request per second and a User-Agent with contact: the same contact as the
Wikipedia client (WIKI_CONTACT). Answers are cached in data/raw/musicbrainz_cache.json.

Usage:
    python -m rg_music.composers [--min-gymnasts 2]
Reads  data/interim/works.csv (python -m rg_music.works --resolve)
Writes data/interim/composer_suggestions.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path
from typing import Callable

import requests

from rg_music.works import ALIASES, _fold, name_tokens, title_key

INTERIM = Path("data/interim")
CACHE = Path("data/raw/musicbrainz_cache.json")
API = "https://musicbrainz.org/ws/2/work"
FIELDS = ["work_key", "work", "n_gymnasts", "our_artists", "confidence", "composers", "mb_title", "mb_id", "alternatives"]
COMPOSER_RELATIONS = {"composer", "writer"}


def composers_of(candidate: dict) -> list[str]:
    seen: list[str] = []
    for rel in candidate.get("relations", []):
        name = rel.get("artist", {}).get("name", "")
        if rel.get("type") in COMPOSER_RELATIONS and name and name not in seen:
            seen.append(name)
    return seen


def choose(work_key: str, our_artists: str, candidates: list[dict]) -> dict:
    """Pick a suggestion from MusicBrainz candidates -> {confidence, composers, mb_title, mb_id, alternatives}."""
    exact = [c for c in candidates if title_key(c.get("title", "")) == work_key and int(c.get("score", 0)) >= 90]
    ours = name_tokens(our_artists)
    for c in exact:
        if composers_of(c) and any(name_tokens(n) & ours for n in composers_of(c)):
            return _pick("high", c, exact)
    if len(exact) == 1:
        return _pick("probable", exact[0], exact)
    if exact:
        return _pick("ambiguous", exact[0], exact)
    return {"confidence": "none", "composers": "", "mb_title": "", "mb_id": "", "alternatives": ""}


def _pick(confidence: str, chosen: dict, exact: list[dict]) -> dict:
    others = [" / ".join(composers_of(c)) or "(no composer)" for c in exact if c is not chosen][:3]
    return {"confidence": confidence, "composers": " / ".join(composers_of(chosen)), "mb_title": chosen.get("title", ""),
            "mb_id": chosen.get("id", ""), "alternatives": " | ".join(others)}


def search(title: str, cache: dict, get: Callable[..., requests.Response], user_agent: str, sleep=time.sleep) -> list[dict]:
    """MusicBrainz work search with a 1.1 s pause; 429/503 (their "slow down") are retried with a longer wait."""
    if title in cache:
        return cache[title]
    for attempt in range(1, 7):
        sleep(1.1)  # MusicBrainz: at most one request per second
        resp = get(API, params={"query": f'work:"{title}"', "fmt": "json", "limit": "8"},
                   headers={"User-Agent": user_agent}, timeout=30)
        if resp.status_code in (429, 503):
            sleep(float(resp.headers.get("Retry-After", 5 * attempt)))
            continue
        resp.raise_for_status()
        cache[title] = resp.json().get("works", [])
        return cache[title]
    raise RuntimeError(f"MusicBrainz kept answering 429/503 for {title!r}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--min-gymnasts", type=int, default=2)
    ap.add_argument("--dir", type=Path, default=INTERIM)
    args = ap.parse_args(argv)

    works = list(csv.DictReader((args.dir / "works.csv").open(encoding="utf-8-sig")))
    known = {r["title_key"] for r in csv.DictReader(ALIASES.open(encoding="utf-8-sig"))} if ALIASES.exists() else set()
    todo = [w for w in works if int(w["n_gymnasts"]) >= args.min_gymnasts and not w["composer"] and w["work_key"] not in known]
    contact = os.environ.get("WIKI_CONTACT", "https://github.com/your-username/rg-music-catalog")
    ua = f"rg-music-catalog/0.1 ({contact}) python-requests/{requests.__version__}"
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    out = []
    try:
        for i, w in enumerate(todo, 1):
            suggestion = choose(w["work_key"], w["artists"], search(w["work"], cache, requests.get, ua))
            out.append({"work_key": w["work_key"], "work": w["work"], "n_gymnasts": w["n_gymnasts"],
                        "our_artists": w["artists"], **suggestion})
            if i % 25 == 0:  # keep what is done if the run dies
                CACHE.parent.mkdir(parents=True, exist_ok=True)
                CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
                print(f"  {i}/{len(todo)}", flush=True)
    finally:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    with (args.dir / "composer_suggestions.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(out)
    from collections import Counter
    print(f"{len(out)} works checked: {dict(Counter(r['confidence'] for r in out))} -> composer_suggestions.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
