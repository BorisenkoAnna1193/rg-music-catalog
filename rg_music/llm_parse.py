"""LLM fallback for music cells the rules could not split (status "unparsed").

The rules (music_parser.py) refuse to guess ambiguous cells such as
"Illumination by Jennifer Thomas, Earth and Fire by Udi Harpaz & Ron Klein". Those few cells go to a
model through OpenRouter, with a strict JSON schema and Pydantic validation:

  * temperature 0, the same conventions as the rules (see SYSTEM);
  * every word of the answer must occur in the source cell, otherwise the track is flagged
    `llm_unverified` (a model must not invent titles or artists);
  * answers are cached (data/raw/llm_cache.json), a second run costs nothing;
  * the rules' tracks.csv is not touched: the model's tracks go to tracks_llm.csv and the merge of
    both to tracks_resolved.csv. A track from the model gets status "llm" (to be glanced at by the
    owner) or "llm_unverified".

Setup (the key never goes into git; .env is git-ignored):
    either   export OPENROUTER_API_KEY=...            # https://openrouter.ai/keys
    or       a file .env in the project root with the line  OPENROUTER_API_KEY=...
    optional OPENROUTER_MODEL=anthropic/claude-sonnet-5.5   (this is the default)
Usage:
    python -m rg_music.llm_parse --dry-run   # show the cells and the request, call nothing
    python -m rg_music.llm_parse
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Callable

import requests
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from rg_music.crosscheck import norm_music

INTERIM = Path("data/interim")
CACHE = Path("data/raw/llm_cache.json")
API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "anthropic/claude-sonnet-5.5"
PROMPT_VERSION = "v1"  # bump to invalidate the cache when SYSTEM changes

SYSTEM = """You split ONE free-text "music" cell from an English Wikipedia article about a rhythmic gymnast into tracks.
Return one object per distinct piece of music, in the order of the cell.

Fields (all strings, "" when unknown):
- title: the track title exactly as written, without surrounding quotes.
- work: the larger work it belongs to, only if the cell says so ("from X", "music from X", "(X OST)").
- artist: everyone credited with "by", "composed by" or "original by"; the composer FIRST, then the other names,
  separated by ", ". Keep the spelling of the cell.
- performer: only people named after "performed by", "conducted by" or "directed by".
- notes: remarks in brackets, "lyrics by X", "remix by X" and similar.

Rules:
- Use ONLY words that appear in the cell. Never translate, correct spelling, add composers or guess.
- "A by X, B and C by Y": the cut between two tracks is where the second TITLE starts; a title may contain commas
  and "and". If the cell is genuinely ambiguous, choose the most natural reading.
- If a track has no credit in the cell, artist is "".

Example cell: Psycho Suite by Bernard Hermann and The Murder by Danny Elfman
Example answer: {"tracks": [{"title": "Psycho Suite", "work": "", "artist": "Bernard Hermann", "performer": "", "notes": ""},
{"title": "The Murder", "work": "", "artist": "Danny Elfman", "performer": "", "notes": ""}]}"""

_STR = {"type": "string"}
SCHEMA = {
    "type": "object",
    "properties": {"tracks": {"type": "array", "items": {
        "type": "object",
        "properties": {k: _STR for k in ("title", "work", "artist", "performer", "notes")},
        "required": ["title", "work", "artist", "performer", "notes"],
        "additionalProperties": False,
    }}},
    "required": ["tracks"],
    "additionalProperties": False,
}


class TrackOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    work: str
    artist: str
    performer: str
    notes: str


class CellOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tracks: list[TrackOut] = Field(min_length=1)


def tokens(text: str) -> set[str]:
    return {t for t in norm_music(text).split() if len(t) >= 3}


def is_verbatim(track: TrackOut, cell: str) -> bool:
    """Every word (3+ letters) of the answer occurs in the cell, and the title is not empty."""
    if not track.title.strip():
        return False
    source = tokens(cell)
    return all(tokens(value) <= source for value in (track.title, track.work, track.artist, track.performer))


class OpenRouter:
    """Minimal OpenRouter client; `post` is injectable so tests never touch the network."""

    def __init__(self, api_key: str, model: str, post: Callable[..., requests.Response] | None = None) -> None:
        self.api_key, self.model, self._post = api_key, model, post or requests.post

    def request_body(self, cell: str) -> dict:
        return {
            "model": self.model, "temperature": 0,
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": cell}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "music_cell", "strict": True, "schema": SCHEMA}},
        }

    def parse_cell(self, cell: str) -> dict:
        body = self.request_body(cell)
        for attempt in range(1, 5):
            resp = self._post(API_URL, json=body, timeout=90,
                              headers={"Authorization": f"Bearer {self.api_key}", "X-Title": "rg-music-catalog"})
            if resp.status_code in (429, 500, 502, 503, 504):
                time.sleep(2 ** attempt)
                continue
            resp.raise_for_status()
            return json.loads(resp.json()["choices"][0]["message"]["content"])
        raise RuntimeError(f"OpenRouter kept failing for: {cell[:60]}")


def cache_key(model: str, cell: str) -> str:
    return hashlib.sha256(f"{PROMPT_VERSION}|{model}|{cell}".encode()).hexdigest()[:24]


def resolve_cells(cells: list[str], client: OpenRouter, cache: dict) -> dict[str, dict]:
    """cell -> {"tracks": [...], "model": ..., "from_cache": bool}; validated with Pydantic."""
    out = {}
    for cell in cells:
        key = cache_key(client.model, cell)
        cached = key in cache
        if not cached:
            cache[key] = client.parse_cell(cell)
        try:
            parsed = CellOut.model_validate(cache[key])
        except ValidationError as exc:
            cache.pop(key, None)  # never keep an invalid answer
            raise RuntimeError(f"model answer does not match the schema for {cell[:60]!r}: {exc}") from exc
        out[cell] = {"tracks": parsed.tracks, "from_cache": cached}
    return out


def merge_resolved(tracks: list[dict], answers: dict[str, dict], model: str) -> tuple[list[dict], list[dict]]:
    """Replace "unparsed" rules tracks with the model's tracks -> (tracks_resolved, tracks_llm)."""
    resolved, llm_rows = [], []
    for row in tracks:
        answer = answers.get(row["raw_text"]) if row["status"] == "unparsed" else None
        if answer is None:
            resolved.append(dict(row))
            continue
        for t in answer["tracks"]:
            ok = is_verbatim(t, row["raw_text"])
            new = {**row, "title": t.title, "work": t.work, "artist": t.artist, "performer": t.performer,
                   "notes": t.notes, "flags": "llm_parsed" + ("" if ok else ";llm_unverified"),
                   "status": "llm" if ok else "llm_unverified"}
            resolved.append(new)
            llm_rows.append({**{k: new[k] for k in ("raw_text", "title", "work", "artist", "performer", "notes")},
                             "verbatim_ok": ok, "model": model})
    counter: dict[str, int] = {}
    for row in resolved:  # renumber: one routine may have gained tracks
        counter[row["routine_id"]] = counter.get(row["routine_id"], 0) + 1
        row["track_no"] = counter[row["routine_id"]]
    return resolved, llm_rows


def load_env_key(env_file: Path = Path(".env"), name: str = "OPENROUTER_API_KEY") -> str:
    """The key from the environment, else from a NAME=value line in .env; "" when absent."""
    if os.environ.get(name):
        return os.environ[name]
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == name:
                return value.strip().strip("\"'")
    return ""


def _read(path: Path) -> list[dict]:
    return list(csv.DictReader(path.open(encoding="utf-8")))


def _write(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dir", type=Path, default=INTERIM)
    ap.add_argument("--dry-run", action="store_true", help="show the cells and the request, call nothing")
    ap.add_argument("--model", default=os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL))
    args = ap.parse_args(argv)

    tracks = _read(args.dir / "tracks.csv")
    cells = list(dict.fromkeys(t["raw_text"] for t in tracks if t["status"] == "unparsed"))
    print(f"{len(cells)} unparsed cells, model {args.model}")
    for c in cells:
        print("  -", c[:110])
    if args.dry_run or not cells:
        if cells:
            print("\nRequest body for the first cell:\n" + json.dumps(OpenRouter("-", args.model).request_body(cells[0]),
                                                                      ensure_ascii=False, indent=1)[:1500])
        return 0
    key = load_env_key()
    if not key:
        print("OPENROUTER_API_KEY is not set: export it, or put OPENROUTER_API_KEY=... into the git-ignored .env file.",
              file=sys.stderr)
        return 2

    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    try:
        answers = resolve_cells(cells, OpenRouter(key, args.model), cache)
    finally:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    resolved, llm_rows = merge_resolved(tracks, answers, args.model)
    _write(args.dir / "tracks_llm.csv", llm_rows, ["raw_text", "title", "work", "artist", "performer", "notes", "verbatim_ok", "model"])
    _write(args.dir / "tracks_resolved.csv", resolved, list(tracks[0]))
    bad = sum(not r["verbatim_ok"] for r in llm_rows)
    print(f"{len(llm_rows)} tracks from the model ({bad} unverified) -> tracks_llm.csv, tracks_resolved.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
