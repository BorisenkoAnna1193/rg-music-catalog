"""Add the official FIG spelling to the rows of the name-review sheet.

Only the gymnasts that are in wc_name_review.csv are looked up. For each of them:
  1. with a Wikipedia article: Wikidata item of that article -> FIG ids
     (P2696 licence number, P7440 biography number);
  2. without an article: Wikidata name search, accepting only results whose
     description mentions "gymnast" and that carry a FIG id (match = name_search,
     less certain - check it);
  3. the FIG profile page gives the name as "SURNAME Given" (page <meta description>).

Usage:
    python -m rg_music.fig_names
Reads data/interim/wc_name_review.csv (left untouched) and writes
    data/interim/wc_name_review_fig.csv   the same rows + wikidata_id, fig_id, fig_name,
                                          fig_name_normalized, fig_match
FIG pages are ~1.3 MB each, so parsed names are cached in data/raw/fig_cache.json.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from pathlib import Path

from .wiki_client import WikiClient

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
FIG_URL = "https://www.gymnastics.sport/site/athletes/bio_detail.php?id={id}{suffix}"
INTERIM = Path("data/interim")
CACHE = Path("data/raw/fig_cache.json")
NEW_FIELDS = ["wikidata_id", "fig_id", "fig_name", "fig_name_normalized", "fig_match"]


class Fetcher:
    """Wikidata + FIG requests with the same User-Agent and 1 req/s as the Wikipedia client."""

    def __init__(self) -> None:
        self.client = WikiClient()
        self.cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}

    def _get(self, url: str, **kw):
        for attempt in range(1, 4):
            self.client._throttle()
            resp = self.client.session.get(url, timeout=self.client.timeout, **kw)
            if resp.status_code in (429, 500, 502, 503, 504):
                time.sleep(float(resp.headers.get("Retry-After", 2**attempt)))
                continue
            resp.raise_for_status()
            return resp
        raise RuntimeError(f"giving up: {url}")

    def wikidata(self, **params) -> dict:
        data = self._get(WIKIDATA_API, params={"format": "json", "maxlag": "5", **params}).json()
        if "error" in data:
            raise RuntimeError(f"Wikidata: {data['error'].get('code')}: {data['error'].get('info')}")
        return data

    def fig_name(self, fig_id: str, kind: str) -> str:
        key = f"{kind}:{fig_id}"
        if key not in self.cache:
            url = FIG_URL.format(id=fig_id, suffix="&type=licence" if kind == "licence" else "")
            m = re.search(r'<meta name="description" content="(.+?) - FIG Athlete Profile"', self._get(url).text)
            self.cache[key] = m.group(1).strip() if m else ""
            CACHE.write_text(json.dumps(self.cache, ensure_ascii=False, indent=1), encoding="utf-8")
        return self.cache[key]


def fig_ids(entity: dict) -> tuple[str, str]:
    """(licence id, biography id) from a Wikidata entity; '' when missing."""
    def first(prop: str) -> str:
        for claim in entity.get("claims", {}).get(prop, []):
            value = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
            if value:
                return str(value)
        return ""
    return first("P2696"), first("P7440")


def normalize_fig_name(name: str) -> str:
    """'AVERINA Dina' -> 'Dina Averina'; upper-case words are the surname."""
    words = name.split()
    surname = [w for w in words if len(w) > 1 and w.isupper()]
    given = [w for w in words if w not in surname]
    if not surname:
        return name
    return " ".join(given + [w.title() for w in surname])


CARRIED = ["decision", "canonical_name", "decision_basis"]


def carry_over(rows: list[dict], previous: list[dict]) -> list[dict]:
    """Keep decisions made earlier (by the owner or by name_decisions) when the sheet is rebuilt."""
    old = {(r["gymnast_key"], r["reason"]): r for r in previous}
    for r in rows:
        before = old.get((r["gymnast_key"], r["reason"]))
        for col in CARRIED:
            r[col] = before.get(col, "") if before else r.get(col, "")
    return rows


def by_wikipedia_title(f: Fetcher, titles: list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for i in range(0, len(titles), 50):
        data = f.wikidata(action="wbgetentities", sites="enwiki", titles="|".join(titles[i:i + 50]),
                          props="claims|sitelinks", sitefilter="enwiki")
        for entity in data.get("entities", {}).values():
            if "sitelinks" in entity:
                out[entity["sitelinks"]["enwiki"]["title"]] = entity
    return out


def by_name_search(f: Fetcher, names: list[str]) -> tuple[dict | None, int]:
    """First gymnast item with a FIG id among the search results, and how many gymnast hits there were."""
    hits: dict[str, str] = {}
    for name in names:
        res = f.wikidata(action="wbsearchentities", search=name, language="en", type="item", limit="7")
        for r in res.get("search", []):
            if re.search(r"gymnast", r.get("description", ""), re.I):
                hits.setdefault(r["id"], r.get("description", ""))
    if not hits:
        return None, 0
    ents = f.wikidata(action="wbgetentities", ids="|".join(hits), props="claims")["entities"]
    for qid in hits:
        if any(fig_ids(ents.get(qid, {}))):
            return {"id": qid, **ents[qid]}, len(hits)
    return None, len(hits)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dir", type=Path, default=INTERIM)
    args = ap.parse_args(argv)

    rows = list(csv.DictReader((args.dir / "wc_name_review.csv").open(encoding="utf-8-sig")))
    f = Fetcher()

    titles = sorted({r["wiki_page"] for r in rows if r["wiki_page"]})
    linked = by_wikipedia_title(f, titles)

    found: dict[str, dict] = {}  # gymnast_key -> info
    for r in rows:
        key = r["gymnast_key"]
        if key in found:
            continue
        entity, match = None, ""
        if r["wiki_page"]:
            entity, match = linked.get(r["wiki_page"]), "wikipedia_link"
        else:
            names = [r["display_name"]] + [s.split(" (")[0] for s in r["spellings"].split(" | ")[:2]]
            entity, n_hits = by_name_search(f, list(dict.fromkeys(names)))
            match = f"name_search ({n_hits} gymnast hits)"
        lic, bio = fig_ids(entity or {})
        fig_id = lic or bio
        name = f.fig_name(fig_id, "licence" if lic else "bio") if fig_id else ""
        found[key] = {
            "wikidata_id": (entity or {}).get("id", ""), "fig_id": fig_id, "fig_name": name,
            "fig_name_normalized": normalize_fig_name(name) if name else "",
            "fig_match": match if fig_id else ("no_fig_id" if entity else "not_found"),
        }
        print(f"{r['display_name']:30} -> {found[key]['fig_name'] or '-':28} {found[key]['fig_match']}")

    out = args.dir / "wc_name_review_fig.csv"
    previous = list(csv.DictReader(out.open(encoding="utf-8-sig"))) if out.exists() else []
    merged = carry_over([{**r, **found[r["gymnast_key"]]} for r in rows], previous)
    fields = list(dict.fromkeys([*rows[0], *NEW_FIELDS, *CARRIED]))
    with out.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(merged)
    got = sum(bool(v["fig_name"]) for v in found.values())
    print(f"\n{len(found)} gymnasts in the review sheet, FIG name found for {got}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
