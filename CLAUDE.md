# CLAUDE.md – context for working on rg-music-catalog

## What this is
A learning pet project for a portfolio (target role: Python data scraping engineer).
A catalog of music used by rhythmic gymnasts, built from English Wikipedia, answering:
1. gymnast → music (by season and apparatus);
2. music → which gymnasts used it, in which year, with which apparatus.

The owner talks in Russian; code, comments, README and commit messages are in English.

## Current state (step 1 done)
- `rg_music/wiki_client.py` – polite MediaWiki API client (UA with contact from
  `WIKI_CONTACT`, 1 req/s, maxlag, retries with Retry-After, redirects, revid, disk cache
  in `data/raw/`, git-ignored).
- `rg_music/tables.py` – finds "Year / Apparatus / Music title" tables (kind `routine`)
  and competition tables with a Music column (kind `competition`); expands
  rowspan/colspan into a grid, then maps columns by header text. `<br>` inside a cell
  becomes " | " unless it is just a wrap before "by"/"from"/"(" etc.; "—" means empty.
  Heuristic fixes are flagged in `notes`, never applied silently.
- `rg_music/events.py` – Olympics get their official name ("Tokyo 2020") and the year
  actually held. Tokyo 2020 → year 2021; rows dated 2020 are corrected and flagged.
- `rg_music/extract.py` – CLI: `python -m rg_music.extract [--refresh] [--titles ...]`
  → `data/interim/routines_raw.csv`, `competitions_raw.csv`, `extract_report.json`.
- `rg_music/crosscheck.py` – compares competition-table music with the routine table
  on the same page → `data/interim/crosscheck.csv`.
- Seed: `data/seed_gymnasts.txt` (10 Olympic AA medalists 2008–2024).
  Last run: 391 routine rows, all 10 pages OK; crosscheck 46 match / 5 fuzzy / 1 differs.
- Tests: `python -m pytest -q` (fixtures mimic real layouts).

## Decisions made with the owner
- **No separate season year vs. event year.** One year = the year the event was held;
  wrong dates in the source are corrected (with a note), not modelled as a second field.
- **Three-level music model**: work (e.g. Spartacus ballet, Khachaturian) → excerpt
  (e.g. Ballet Suite No. 2: Adagio of Spartacus and Phrygia) → recording/performer.
  If the excerpt is not stated it is *unknown*, never assumed equal to another excerpt
  (Mamun 2014 hoop names the Adagio; Averina 2018 hoop names only the ballet).
- Keep raw data untouched in `*_raw.csv`; every cleaning step writes new files.

## Next: step 2 – parse the free-text music cell
Split into tracks, then each track into title / work / excerpt / composer / performer.
Formats seen: `"X" by Y`, `X by Y`, `"X", by Y` (Kanaeva), `X as composed by Y`,
`X, composed by Y by Z`, `X (from Y) by Z`, `X music from Y by Z`,
`original by A, remix by B`, `(performed by C)`, several tracks joined by `,` `/` `;`
or " | ", no "by" at all (27 rows), references like "(same music as CariPrato 2007)".
Plan: regex rules first, report coverage, then an LLM fallback (OpenRouter, strict JSON
schema, Pydantic validation, cached) for rows the rules cannot parse.
Also normalise ~40 apparatus spellings: "Hoop (2nd)", "Ribbons", "Clubs (Second)",
"Gala at EC Minsk", "Clubs (Aeon Cup)", "Gala-2 Ribbons (WCH Patras)" → apparatus +
variant (first/second/third) + context.

Known source errors worth catching in validation: Averina 2015 "Giselle" attributed to
Tchaikovsky (it is Adam); "Mvrica" (Mrvica); Kudryavtseva 2016 ball "from Toy Story 4"
only in one of two tables; Kanaeva 2012 "Fantasie Impromptu No 66" (Op. 66).

## Later steps
Entity resolution across gymnasts (rapidfuzz + MusicBrainz + LLM arbiter), validation
(years vs. career from Wikidata, apparatus vocabulary), Wikidata as second source for
gymnast list, archived rgforum.no via Wayback, exports (CSV/JSON/Google Sheets/SQLite),
search UI, Docker + scheduled run + S3.
