"""Author proposals for the works: author_type, author, lyrics, "from a film" (for the owner's review; nothing applied).

Owner's rules (2026-10-07): classical, jazz standards, tango, film scores and musicals -> the COMPOSER is the author;
folk -> "folk music"; a pop song -> no author on the work (the performers are its versions). `from_title` /
`from_type` only for music written for a film / musical / series / game, not an old song used in one.

Works reviewed: every work used by 2+ gymnasts, plus classical works without a composer. For each, a MusicBrainz work
is chosen (data/raw caches; at most 1 request per second):
  known       the MusicBrainz work that mb_works.py linked to this work's tracks
  credit      a work with this title whose composer / writer / lyricist is credited in our data
  single      the only work with exactly this title (score 90+)
  most_recorded  several works with this title: the one with the most recordings. Often another song (Rush's
              "Limelight", Alex North's "Spartacus"), so it is only shown with "?" and never used for the proposal
  none        nothing with this title
For a classical work whose composer we know, MusicBrainz is used only when its writers include that composer (titles
like "Don Quixote" find the novel); without a known composer a trusted match gives it (Fantaisie-Impromptu -> Chopin).
From it: the type (Song, Soundtrack, Ballet...), lyrics (language "zxx" = no words; needed for the FIG rule on music
with words) and the writers. The proposal, first rule that applies:
  folk       owner alias "folk music", folk / traditional in the credits or the title, or MusicBrainz "[traditional]"
  composer   classical (composer from the owner's lists), an owner alias with a composer, a MusicBrainz work without
             words or of type Soundtrack / Ballet / Opera / Musical...
  composer   ...or a work without type or language whose MusicBrainz writer is the credited name (Concerto de Berlin)
  performer  a MusicBrainz song with words, or of type Song with no language (pop rule: no author on the work)
  unknown    nothing found
`from_title` is proposed from the "music from X" / "(X OST)" part of the cells only when a cell says OST / film /
soundtrack / musical / series / game, or the MusicBrainz work is a Soundtrack / Musical ("music from Origin of Symmetry"
is an album), for the owner to confirm.

The owner reviews the proposals in Google Sheets (work_authors_review); --import reads that sheet exported as CSV and
writes data/manual/work_authors.csv, one row per work: the owner's values where she changed a row (source owner), the
proposal elsewhere (source proposal, or rule for classical / owner-alias composers that were not in the sheet). On the
way: author_type is lower-cased; folk gets the author "folk music"; a name typed as the author of a `performer` work is
its ORIGINAL performer (pop works show no author), as is "original: X" in owner_note. Then
data/manual/work_author_corrections.csv (work_key, field, value, reason) is applied on top: Claude's fixes of typos and
of values that break the owner's rules, each with its reason, so the owner can drop any of them.

Usage:
    python -m rg_music.work_authors
    python -m rg_music.work_authors --import <sheet exported as csv>
Reads  data/interim/works.csv, track_works.csv, tracks.csv, work_mb_links.csv, data/manual/work_aliases.csv
Writes data/interim/work_author_proposals.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import requests

from rg_music.composers import CACHE as WORK_CACHE
from rg_music.composers import composers_of, search as search_works
from rg_music.mb_works import API, REC_CACHE, get_json, same_name
from rg_music.works import ALIASES, _CREDIT_SPLIT, title_key

INTERIM = Path("data/interim")
AUTHORS = Path("data/manual/work_authors.csv")
CORRECTIONS = Path("data/manual/work_author_corrections.csv")
AUTHOR_FIELDS = ["work_key", "work", "author_type", "author", "original_performer", "from_title", "from_type",
                 "has_lyrics", "source", "owner_note"]
EDITABLE = ["author_type", "author", "from_title", "from_type", "owner_note"]
FIELDS = ["row_id", "work_key", "work", "n_gymnasts", "is_classical", "our_credits", "mb_match", "mb_type",
          "has_lyrics", "match", "author_type", "author", "from_title", "from_type", "basis", "owner_note"]
WRITER_RELATIONS = {"composer", "writer", "lyricist"}
COMPOSER_TYPES = {"Soundtrack", "Ballet", "Opera", "Musical", "Overture", "Suite", "Concerto", "Symphony",
                  "Symphonic poem", "Zarzuela", "Operetta", "Sonata", "Etude", "Mass", "Aria", "Madrigal"}
FOLK = re.compile(r"\bfolk\b|\btraditional\b|народн", re.I)
SCREEN = re.compile(r"\bOST\b|soundtrack|\bfilm\b|movie|musical|broadway|series|\bTV\b|\bgame\b", re.I)
TRUSTED = {"known", "credit", "single"}


def writers_of(work: dict) -> list[str]:
    seen: list[str] = []
    for rel in work.get("relations", []):
        name = rel.get("artist", {}).get("name", "")
        if rel.get("type") in WRITER_RELATIONS and name and name not in seen:
            seen.append(name)
    return seen


def n_recordings(work: dict) -> int:
    return sum(rel.get("type") == "performance" for rel in work.get("relations", []))


def has_lyrics(work: dict | None) -> str:
    if not work:
        return ""
    langs = set(work.get("languages") or []) | ({work["language"]} if work.get("language") else set())
    return "" if not langs else "no" if langs == {"zxx"} else "yes"


def choose_work(key: str, credits: list[str], candidates: list[dict], known: dict | None) -> tuple[dict | None, str]:
    """-> (MusicBrainz work, how it was chosen)."""
    if known:
        return known, "known"
    exact = [c for c in candidates if title_key(c.get("title", "")) == key and int(c.get("score", 0)) >= 90]
    for c in exact:
        if any(same_name(credit, w) or same_name(w, credit) for credit in credits for w in writers_of(c)):
            return c, "credit"
    if len(exact) == 1:
        return exact[0], "single"
    if exact:
        return max(exact, key=n_recordings), "most_recorded"
    return None, "none"


def from_title_hint(cells: list[str], parsed_works: list[str], screen_work: bool = False) -> tuple[str, str]:
    """'music from Moulin Rouge!', '(Cleopatra OST)' -> (title, type guess); the owner confirms."""
    title = Counter(w for w in parsed_works if w).most_common(1)
    text = " ".join(cells)
    if not title or not (screen_work or SCREEN.search(text)):
        return "", ""
    kind = ("musical" if re.search(r"musical|broadway|cast", text, re.I) else
            "series" if re.search(r"series|\bTV\b|television", text, re.I) else
            "game" if re.search(r"\bgame\b", text, re.I) else "film")
    clean = re.sub(r"^(?:the\s+)?(?:film|movie)\s+|\s*\(?\b(?:OST|film|movie)\b\)?\s*$", "", title[0][0], flags=re.I)
    return clean.strip(), kind


def propose(work: dict, alias_composer: str, credits: list[str], titles: list[str], mb: dict | None) -> tuple[str, str, str]:
    """-> (author_type, author, basis)."""
    writers = writers_of(mb) if mb else []
    if alias_composer.lower() == "folk music" or any(FOLK.search(x) for x in credits + titles + writers):
        return "folk", "folk music", "folk in an alias, the credits or the title"
    if work["is_classical"] == "1":
        return "composer", alias_composer or work["classical_composer"] or work["composer"] or " / ".join(writers), "classical"
    if alias_composer:
        return "composer", alias_composer, "owner alias"
    if mb and (has_lyrics(mb) == "no" or mb.get("type") in COMPOSER_TYPES):
        return "composer", " / ".join(writers), f"MusicBrainz: {mb.get('type') or 'no words'}"
    if mb and has_lyrics(mb) == "yes":
        return "performer", "", "MusicBrainz: song with words (pop rule)"
    if mb and mb.get("type") == "Song":
        return "performer", "", "MusicBrainz: Song, language not given (pop rule)"
    if mb and any(same_name(c, w) or same_name(w, c) for c in credits for w in writers):
        return "composer", " / ".join(writers), "MusicBrainz writer is the credited name"
    if mb:
        return "unknown", "", "MusicBrainz: no type or language"
    return "unknown", "", "not found in MusicBrainz"


def import_sheet(sheet: list[dict], proposals: list[dict], corrections: list[dict]) -> list[dict]:
    """Owner's sheet + the proposals not in it + Claude's corrections -> one author row per work."""
    out: dict[str, dict] = {}
    for p in proposals:
        out[p["work_key"]] = {"work_key": p["work_key"], "work": p["work"], "author_type": p["author_type"],
                              "author": p["author"], "original_performer": "", "from_title": p["from_title"],
                              "from_type": p["from_type"], "has_lyrics": p["has_lyrics"], "owner_note": "",
                              "source": "rule" if p["basis"] in ("classical", "owner alias") and p["author"] else "proposal"}
    by_id = {p["row_id"]: p for p in proposals}
    for s in sheet:
        p = by_id[s["row_id"]]
        row = out[p["work_key"]]
        if not any(s[k].strip() != p[k].strip() for k in EDITABLE):
            continue
        note = s["owner_note"].strip()
        row.update({k: s[k].strip() for k in EDITABLE}, source="owner")
        row["author_type"] = row["author_type"].lower()
        if m := re.match(r"original:\s*(.+)$", note, re.I):
            row["original_performer"] = m.group(1).strip()
        if row["author_type"] == "performer" and row["author"]:
            row["original_performer"] = row["original_performer"] or row["author"]
            row["author"] = ""
    for row in out.values():
        if row["author_type"] == "folk" and not row["author"]:
            row["author"] = "folk music"
    for c in corrections:
        if c["work_key"] in out:
            out[c["work_key"]][c["field"]] = c["value"]
            out[c["work_key"]]["owner_note"] = "; ".join(filter(None, [out[c["work_key"]]["owner_note"], c["reason"]]))
    return sorted(out.values(), key=lambda r: r["work_key"])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dir", type=Path, default=INTERIM)
    ap.add_argument("--import", dest="sheet", type=Path, help="the owner's review sheet exported as CSV")
    args = ap.parse_args(argv)
    read = lambda name: list(csv.DictReader((args.dir / name).open(encoding="utf-8-sig")))  # noqa: E731
    if args.sheet:
        corrections = list(csv.DictReader(CORRECTIONS.open(encoding="utf-8-sig"))) if CORRECTIONS.exists() else []
        rows = import_sheet(list(csv.DictReader(args.sheet.open(encoding="utf-8-sig"))), read("work_author_proposals.csv"),
                            corrections)
        with AUTHORS.open("w", newline="", encoding="utf-8-sig") as f:
            wr = csv.DictWriter(f, fieldnames=AUTHOR_FIELDS)
            wr.writeheader()
            wr.writerows(rows)
        print(f"{len(rows)} works -> {AUTHORS}: source {dict(Counter(r['source'] for r in rows))}; "
              f"author_type {dict(Counter(r['author_type'] for r in rows))}")
        return 0

    works = read("works.csv")
    todo = [w for w in works if int(w["n_gymnasts"]) >= 2
            or (w["is_classical"] == "1" and not (w["composer"] or w["classical_composer"]))]
    tracks = {(t["routine_id"], t["track_no"]): t for t in read("tracks.csv")}
    by_work: dict[str, list[dict]] = defaultdict(list)
    for t in read("track_works.csv"):
        by_work[t["work_key"]].append(t)
    link_ids = {r["work_key"]: r["mb_work_id"] for r in read("work_mb_links.csv") if r["mb_work_id"]}
    alias_composer = {}
    for a in csv.DictReader(ALIASES.open(encoding="utf-8-sig")):
        if a["composer"]:
            alias_composer.setdefault(a.get("work_key") or title_key(a["work"]), a["composer"])

    contact = os.environ.get("WIKI_CONTACT", "https://github.com/your-username/rg-music-catalog")
    ua = f"rg-music-catalog/0.1 ({contact}) python-requests/{requests.__version__}"
    work_cache = json.loads(WORK_CACHE.read_text(encoding="utf-8")) if WORK_CACHE.exists() else {}
    rec_cache = json.loads(REC_CACHE.read_text(encoding="utf-8")) if REC_CACHE.exists() else {}
    out = []
    try:
        for i, w in enumerate(todo, 1):
            ts = by_work[w["work_key"]]
            credits = [c for c in dict.fromkeys(t["artist"] for t in ts) if c]
            names = [n.strip() for c in credits for n in re.split(_CREDIT_SPLIT, c) if n.strip()]
            candidates = search_works(w["work"], work_cache, requests.get, ua)
            ids = Counter(link_ids[t["split_key"]] for t in ts if t["split_key"] in link_ids)
            known = None
            if ids:
                wid = ids.most_common(1)[0][0]
                known = next((c for c in candidates if c.get("id") == wid), None) or get_json(
                    f"{API}/work/{wid}", {"inc": "artist-rels"}, rec_cache, f"workinfo|{wid}", requests.get, ua) or None
            mb, how = choose_work(title_key(w["work"]), names, candidates, known)
            if w["is_classical"] == "1" and mb and (w["classical_composer"] or w["composer"]) and not any(
                    same_name(c, x) or same_name(x, c) for c in names + [w["classical_composer"], w["composer"]] if c
                    for x in writers_of(mb)):
                how = "classical_mismatch"
            shown, mb = mb, (mb if how in TRUSTED else None)
            cells = [tracks[(t["routine_id"], t["track_no"])]["raw_text"] for t in ts]
            akey = alias_composer.get(w["work_key"], "")
            author_type, author, basis = propose(w, akey, names, [t["title"] for t in ts], mb)
            ft, fk = ("", "") if w["is_classical"] == "1" else from_title_hint(
                cells, [tracks[(t["routine_id"], t["track_no"])]["work"] for t in ts],
                (mb or {}).get("type") in {"Soundtrack", "Musical"})
            out.append({
                "row_id": i, "work_key": w["work_key"], "work": w["work"], "n_gymnasts": w["n_gymnasts"],
                "is_classical": w["is_classical"], "our_credits": " | ".join(credits[:3])[:80],
                "mb_match": ("" if mb else "? ") + f"{shown.get('title', '')} — {' / '.join(writers_of(shown))}"[:78] if shown else "",
                "mb_type": (mb or {}).get("type") or "", "has_lyrics": has_lyrics(mb), "match": how,
                "author_type": author_type, "author": author, "from_title": ft, "from_type": fk, "basis": basis,
                "owner_note": "",
            })
            if i % 25 == 0:
                WORK_CACHE.write_text(json.dumps(work_cache, ensure_ascii=False), encoding="utf-8")
                REC_CACHE.write_text(json.dumps(rec_cache, ensure_ascii=False), encoding="utf-8")
                print(f"  {i}/{len(todo)}", flush=True)
    finally:
        WORK_CACHE.write_text(json.dumps(work_cache, ensure_ascii=False), encoding="utf-8")
        REC_CACHE.write_text(json.dumps(rec_cache, ensure_ascii=False), encoding="utf-8")
    with (args.dir / "work_author_proposals.csv").open("w", newline="", encoding="utf-8-sig") as f:
        wr = csv.DictWriter(f, fieldnames=FIELDS)
        wr.writeheader()
        wr.writerows(out)
    print(f"{len(out)} works: author_type {dict(Counter(r['author_type'] for r in out))}; "
          f"match {dict(Counter(r['match'] for r in out))}; lyrics {dict(Counter(r['has_lyrics'] for r in out))}; "
          f"from_title proposed {sum(bool(r['from_title']) for r in out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
