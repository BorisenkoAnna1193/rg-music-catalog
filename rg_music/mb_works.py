"""MusicBrainz evidence for titles that were split by credit: are "Feeling Good" by Muse and by Michael Bublé one song?

works.py splits one title into separate works when the credits share no name (owner, 2026-10-07: no merge without
evidence). This step looks for that evidence. For every split group (one work "<title> ~ <main credit>"):

  recording        a MusicBrainz recording with the same title by the credited performer, and the work that
                   recording is a performance of (recording -> work link)
  credited_author  the credit names an author of a MusicBrainz work with that title ("Besame Mucho by Consuelo
                   Velázquez": the cell names the composer, not a performer)
  work_recording   second pass, for the groups still without evidence: the performer is among the recordings of a
                   MusicBrainz work with that title (covers often have no recording -> work link, but the work lists
                   them: "Smooth Criminal" by David Garrett). The works tried are the ones found for other groups of
                   the title, then the works with exactly that title from the work search (at most MAX_WORKS).
  none             neither
A name matches when every word of the first credited name is in the MusicBrainz name ("Jay Hawkins" = "Screamin' Jay
Hawkins"), or both are one name spelled apart ("2 Cellos" = "2Cellos"): a shared first name is not enough.

Groups of one title that point to the same MusicBrainz work are proposed as one work (work_mb_proposals.csv);
nothing is applied here.

MusicBrainz asks for at most 1 request per second and a User-Agent with contact (WIKI_CONTACT, as for Wikipedia).
Answers are cached in data/raw/musicbrainz_cache.json (work searches, shared with composers.py) and
data/raw/musicbrainz_recordings.json (recording searches and lookups).

Usage:
    python -m rg_music.mb_works
Reads  data/interim/track_works.csv (python -m rg_music.works --resolve)
Writes data/interim/work_mb_links.csv (one row per split group), work_mb_proposals.csv (one row per title)
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Callable

import requests

from rg_music.composers import CACHE as WORK_CACHE
from rg_music.composers import composers_of, search as search_works
from rg_music.works import _CREDIT_SPLIT, name_tokens, performer_key, title_key

INTERIM = Path("data/interim")
REC_CACHE = Path("data/raw/musicbrainz_recordings.json")
API = "https://musicbrainz.org/ws/2"
LINK_FIELDS = ["title_cluster", "work_key", "title", "credit", "n_gymnasts", "evidence", "mb_work_id", "mb_work_title",
               "mb_writers", "mb_recording_id", "mb_recording_title", "mb_recording_artist"]
MAX_WORKS = 4
PROPOSAL_FIELDS = ["title_cluster", "n_groups", "n_found", "proposal", "joined", "apart", "not_found"]


def _lucene(text: str) -> str:
    return re.sub(r'["\\]', " ", text).strip()


def main_name(credit: str) -> str:
    """First credited name: 'Michel Camilo / Jorge Pardo' -> 'Michel Camilo', 'Calvin Harris feat Rihanna' -> 'Calvin Harris'."""
    first = re.split(_CREDIT_SPLIT, credit)[0]
    return re.split(r"\s+(?:feat\.?|ft\.?|featuring|with)\s+", first, flags=re.I)[0].strip()


def same_name(credit: str, name: str) -> bool:
    """Every word of the first credited name occurs in name, or they are one name spelled apart."""
    ours = name_tokens(main_name(credit))
    return bool(ours) and ours <= name_tokens(name) or performer_key(main_name(credit)) == performer_key(name)


def get_json(url: str, params: dict, cache: dict, key: str, get: Callable[..., requests.Response], user_agent: str,
             sleep=time.sleep):
    """GET with a 1.1 s pause and retries on 429/503 (MusicBrainz's "slow down"); cached under key."""
    if key in cache:
        return cache[key]
    for attempt in range(1, 7):
        sleep(1.1)
        resp = get(url, params={**params, "fmt": "json"}, headers={"User-Agent": user_agent}, timeout=30)
        if resp.status_code in (429, 503):
            sleep(float(resp.headers.get("Retry-After", 5 * attempt)))
            continue
        if resp.status_code == 404:
            cache[key] = {}
            return cache[key]
        resp.raise_for_status()
        cache[key] = resp.json()
        return cache[key]
    raise RuntimeError(f"MusicBrainz kept answering 429/503 for {key!r}")


def matching_recordings(cluster: str, credit: str, recordings: list[dict]) -> list[dict]:
    """Recordings with the same title (normalised) whose artist credit shares a name with ours, best score first."""
    out = []
    for r in recordings:
        artists = " ".join(a.get("name", "") for a in r.get("artist-credit", []))
        if int(r.get("score", 0)) >= 80 and title_key(r.get("title", "")) == cluster and same_name(credit, artists):
            out.append(r)
    return sorted(out, key=lambda r: -int(r.get("score", 0)))


def works_of_recording(lookup: dict) -> list[dict]:
    return [rel["work"] for rel in lookup.get("relations", []) if rel.get("type") == "performance" and rel.get("work")]


def credited_author_work(cluster: str, credit: str, works: list[dict]) -> dict | None:
    """A MusicBrainz work with this title whose composer/writer is the credited name."""
    for w in works:
        if title_key(w.get("title", "")) == cluster and any(same_name(credit, n) for n in composers_of(w)):
            return w
    return None


def groups_to_check(track_works: list[dict], routines: dict[str, dict]) -> list[dict]:
    """One row per work made by the split (not the 'no credit' leftovers): title, main credit, gymnasts."""
    by: dict[str, list[dict]] = defaultdict(list)
    for t in track_works:
        if t["split_key"]:  # the group as split, also when a previous run joined it again
            by[t["split_key"]].append(t)
    out = []
    for key, ts in sorted(by.items()):
        credit = sorted(Counter(t["artist"] for t in ts).items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        out.append({"title_cluster": ts[0]["title_cluster"], "work_key": key,
                    "title": Counter(t["title"] for t in ts).most_common(1)[0][0], "credit": credit if name_tokens(credit) else "",
                    "n_gymnasts": len({routines[t["routine_id"]]["gymnast_page"] for t in ts})})
    return out


def find_evidence(group: dict, fetch: Callable[[str, dict, str], dict], fetch_works: Callable[[str], list[dict]]) -> dict:
    empty = {"evidence": "none", "mb_work_id": "", "mb_work_title": "", "mb_writers": "", "mb_recording_id": "",
             "mb_recording_title": "", "mb_recording_artist": ""}
    if not group["credit"]:
        return empty
    cluster, credit = group["title_cluster"], group["credit"]
    works = fetch_works(group["title"])
    if w := credited_author_work(cluster, credit, works):
        return {**empty, "evidence": "credited_author", "mb_work_id": w["id"], "mb_work_title": w.get("title", ""),
                "mb_writers": " / ".join(composers_of(w))}
    found = fetch(f"{API}/recording", {"query": f'recording:"{_lucene(group["title"])}" AND artist:"{_lucene(main_name(credit))}"',
                                       "limit": "10"}, f"search|{group['title']}|{main_name(credit)}")
    for rec in matching_recordings(cluster, credit, found.get("recordings", []))[:2]:
        linked = works_of_recording(fetch(f"{API}/recording/{rec['id']}", {"inc": "work-rels"}, f"rec|{rec['id']}"))
        if linked:
            w = linked[0]
            writers = next((composers_of(x) for x in works if x.get("id") == w["id"]), [])
            return {**empty, "evidence": "recording", "mb_work_id": w["id"], "mb_work_title": w.get("title", ""),
                    "mb_writers": " / ".join(writers), "mb_recording_id": rec["id"], "mb_recording_title": rec.get("title", ""),
                    "mb_recording_artist": " ".join(a.get("name", "") for a in rec.get("artist-credit", []))}
    return empty


def performers_of_work(lookup: dict) -> list[str]:
    return [" ".join(a.get("name", "") for a in rel["recording"].get("artist-credit", []))
            for rel in lookup.get("relations", []) if rel.get("recording")]


def fill_from_work_recordings(links: list[dict], fetch: Callable[[str, dict, str], dict],
                              fetch_works: Callable[[str], list[dict]]) -> None:
    """Second pass: a group still without evidence joins a MusicBrainz work that lists a recording by its performer."""
    by: dict[str, list[dict]] = defaultdict(list)
    for link in links:
        by[link["title_cluster"]].append(link)
    for cluster, ls in by.items():
        todo = [x for x in ls if x["evidence"] == "none" and x["credit"]]
        if not todo:
            continue
        found = {x["mb_work_id"]: (x["mb_work_title"], x["mb_writers"]) for x in ls if x["mb_work_id"]}
        searched = [w for w in fetch_works(ls[0]["title"]) if title_key(w.get("title", "")) == cluster
                    and int(w.get("score", 0)) >= 90]
        for w in searched:
            found.setdefault(w["id"], (w.get("title", ""), " / ".join(composers_of(w))))
        for wid, (title, writers) in list(found.items())[:MAX_WORKS]:
            performers = performers_of_work(fetch(f"{API}/work/{wid}", {"inc": "recording-rels artist-credits"}, f"work|{wid}"))
            for x in todo:
                if x["evidence"] == "none" and any(same_name(x["credit"], p) for p in performers):
                    x.update(evidence="work_recording", mb_work_id=wid, mb_work_title=title, mb_writers=writers)


def proposals(links: list[dict]) -> list[dict]:
    """Per title: which groups point to the same MusicBrainz work (-> one work), which to different ones."""
    by: dict[str, list[dict]] = defaultdict(list)
    for link in links:
        by[link["title_cluster"]].append(link)
    out = []
    for cluster, ls in sorted(by.items()):
        per_work: dict[str, list[str]] = defaultdict(list)
        for link in ls:
            if link["mb_work_id"]:
                per_work[link["mb_work_id"]].append(link["work_key"])
        joined = [ks for ks in per_work.values() if len(ks) > 1]
        out.append({
            "title_cluster": cluster, "n_groups": len(ls), "n_found": sum(bool(x["mb_work_id"]) for x in ls),
            "proposal": "join" if joined else "apart" if len(per_work) > 1 else "no evidence",
            "joined": " || ".join(" + ".join(ks) for ks in joined),
            "apart": " || ".join(ks[0] for ks in per_work.values() if len(ks) == 1),
            "not_found": " || ".join(x["work_key"] for x in ls if not x["mb_work_id"]),
        })
    return out


def _write(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dir", type=Path, default=INTERIM)
    args = ap.parse_args(argv)

    read = lambda name: list(csv.DictReader((args.dir / name).open(encoding="utf-8-sig")))  # noqa: E731
    routines = {r["routine_id"]: r for r in read("routines_parsed.csv")}
    groups = groups_to_check(read("track_works.csv"), routines)
    contact = os.environ.get("WIKI_CONTACT", "https://github.com/your-username/rg-music-catalog")
    ua = f"rg-music-catalog/0.1 ({contact}) python-requests/{requests.__version__}"
    work_cache = json.loads(WORK_CACHE.read_text(encoding="utf-8")) if WORK_CACHE.exists() else {}
    rec_cache = json.loads(REC_CACHE.read_text(encoding="utf-8")) if REC_CACHE.exists() else {}

    def save() -> None:
        REC_CACHE.parent.mkdir(parents=True, exist_ok=True)
        WORK_CACHE.write_text(json.dumps(work_cache, ensure_ascii=False), encoding="utf-8")
        REC_CACHE.write_text(json.dumps(rec_cache, ensure_ascii=False), encoding="utf-8")

    fetch = lambda url, params, key: get_json(url, params, rec_cache, key, requests.get, ua)  # noqa: E731
    fetch_works = lambda title: search_works(title, work_cache, requests.get, ua)  # noqa: E731
    links = []
    try:
        for i, g in enumerate(groups, 1):
            links.append({**g, **find_evidence(g, fetch, fetch_works)})
            if i % 25 == 0:
                save()
                print(f"  {i}/{len(groups)}", flush=True)
        fill_from_work_recordings(links, fetch, fetch_works)
    finally:
        save()
    props = proposals(links)
    _write(args.dir / "work_mb_links.csv", LINK_FIELDS, links)
    _write(args.dir / "work_mb_proposals.csv", PROPOSAL_FIELDS, props)
    print(f"{len(links)} split groups: {dict(Counter(x['evidence'] for x in links))}; "
          f"{len(props)} titles: {dict(Counter(p['proposal'] for p in props))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
