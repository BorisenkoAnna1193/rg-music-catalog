# CLAUDE.md – context for working on rg-music-catalog

## What this is
A learning pet project for a portfolio (target role: Python data scraping engineer).
A catalog of music used by rhythmic gymnasts, built from English Wikipedia, answering:
1. gymnast → music (by season and apparatus);
2. music → which gymnasts used it, in which year, with which apparatus.

The owner talks in Russian; code, comments, README and commit messages are in English.

## Current state (steps 1 and 2 done)
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
- `rg_music/apparatus.py` – ~40 apparatus spellings → apparatus + variant
  (first/second/third) + context ("Gala at EC Minsk" → Gala / "EC Minsk"); typos fixed with a note.
- `rg_music/music_parser.py` – rule-based parser of the music cell → tracks (title, work,
  artist, performer, notes, flags, status). `rg_music/parse.py` – CLI: `python -m rg_music.parse`
  → `data/interim/routines_parsed.csv` (one row per routine), `tracks.csv` (one row per track,
  key `routine_id` = gymnast_page|table_index|row_index), `parse_report.json`.
  Last run: 391 routines → 403 tracks: 382 ok, 20 partial (all "no credit in source"), 1 reference.
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

## Decisions for step 2 (made with the owner)
- **`artist` = composer + performer credited with "by"**, composer first, comma-separated
  ("Georgy Sviridov, Alexander Vedernikov & Russian Philharmonic Symphony Orchestra").
  Separate `performer` only for explicit "performed/conducted by". Telling them apart is
  left to entity resolution.
- **`excerpt` column dropped** (rules cannot fill it); the three-level model stays as a
  goal, add the column back when something can fill it.
- **Several works in one cell → several tracks with the same `routine_id`**:
  "A by X and B by Y" (flag `split_multiple_by`), "A / B by X / Y" paired by position
  (flag `slash_split`); unequal counts stay one-credit-shared and `partial`.
  Remix: title "Poeta (remix by B)", artist = original artist.
- **Status**: `partial` only for `no_credit` / `slash_in_credit`; other flags
  (`comma_in_title`, `credit_without_by`, `unbalanced_quote`, `remix`) are informational.
- `no_credit` tracks (20, e.g. "Russian Folk", "Basement Jaxx") are kept as is; enrich later
  from another source.
- Pipeline layers: `*_raw.csv` → parsed CSV → owner-reviewed CSV (corrections in a separate
  `overrides.csv` keyed by id, so re-running the parser never loses them) → SQLite loaded
  idempotently only from the reviewed layer.

## Next
1. Owner review of `tracks.csv` + `overrides.csv` mechanism.
2. Second source: rgforum.no music list (archived on Wayback, last snapshot ~2022; the
   live site does not resolve). Check ToS/robots, 1 req/s; use it to cross-check Wikipedia
   and to enrich `no_credit` tracks. LLM fallback only if rules prove insufficient.
3. SQLite schema + loader.

Known source errors worth catching in validation: Averina 2015 "Giselle" attributed to
Tchaikovsky (it is Adam); "Mvrica" (Mrvica); Kudryavtseva 2016 ball "from Toy Story 4"
only in one of two tables; Kanaeva 2012 "Fantasie Impromptu No 66" (Op. 66).

## Later steps
Entity resolution (same music across gymnasts, composer vs. performer) (rapidfuzz + MusicBrainz + LLM arbiter), validation
(years vs. career from Wikidata, apparatus vocabulary), Wikidata as second source for
gymnast list, exports (CSV/JSON/Google Sheets/SQLite),
search UI, Docker + scheduled run + S3.
