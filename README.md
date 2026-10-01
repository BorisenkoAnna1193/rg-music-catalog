# rg-music-catalog

A searchable catalog of the music used by rhythmic gymnasts in their routines,
built from English Wikipedia.

Two questions it should answer:

1. **Gymnast → music**: what did a gymnast perform to, by season and apparatus?
2. **Music → gymnasts**: who used a given piece, in which year, with which apparatus?

The second question is the hard part. The same music is written down in many
different ways across articles, so the project is mostly about data cleaning,
normalisation and entity resolution, not just downloading pages.

## Status

- [x] **Step 1 – extract.** Download gymnast articles through the MediaWiki API
  and dump their music tables as-is.
- [x] **Cross-check** the routine table against the competition (Olympic) table on
  the same page (`python -m rg_music.crosscheck`). First run on 10 pages: 52 Olympic
  routines, 46 match exactly or near-exactly, 5 match but one season later
  (Tokyo 2020 was held in 2021 – the table labels the Games, not the season),
  1 differs in detail only (composer vs. arranger listed).
- [x] **Step 2 – parse (rules).** Split the music cell into tracks (title / work / artist /
  performer) and normalise apparatus (`python -m rg_music.parse`). 391 routines → 403 tracks;
  20 tracks have no credit in the source. LLM fallback is not needed for the current data.
- [ ] Step 3 – match the same music across gymnasts.
- [ ] Step 4 – validation, cross-source checks, export, search UI.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export WIKI_CONTACT="https://github.com/<you>/rg-music-catalog"   # goes into the User-Agent
python -m rg_music.extract          # pages from data/seed_gymnasts.txt
python -m rg_music.parse            # raw -> parsed routines and tracks
python -m pytest -q
```

Outputs go to `data/interim/`:

| file | contents |
|---|---|
| `routines_raw.csv` | one row per row of a "Year / Apparatus / Music title" table |
| `competitions_raw.csv` | rows of competition tables that have a Music column (e.g. Olympics) |
| `extract_report.json` | what was found on every page: tables, headers, redirects, errors |
| `routines_parsed.csv` | one row per routine: normalised apparatus / variant / context, parse status |
| `tracks.csv` | one row per track, keyed by `routine_id`; `flags` show which heuristics were applied |
| `parse_report.json` | parse coverage and flag counts |

Downloaded HTML is cached in `data/raw/` (git-ignored); `--refresh` re-downloads.

## How the extractor works

- **Polite API client** (`rg_music/wiki_client.py`): descriptive User-Agent,
  one request per second, `maxlag`, retries with exponential backoff that respect
  `Retry-After`, redirects followed (`Ganna Rizatdinova` → `Hanna Rizatdinova`),
  revision id stored for every page so later runs can be incremental.
- **Layout-agnostic table parser** (`rg_music/tables.py`): the tables are
  hand-edited and their layout drifts between pages – years spanning several
  rows, a year sitting alone in its own row, footnotes, several tracks separated
  by line breaks. Every table is first expanded into a plain grid
  (`rowspan`/`colspan` resolved) and only then columns are mapped by header text.
  Rows that needed a heuristic fix are flagged in the `notes` column rather than
  silently patched.

## Data model (planned)

Matching music needs three levels, not one:

```
work      Spartacus (ballet), Aram Khachaturian
  excerpt   Ballet Suite No. 2: Adagio of Spartacus and Phrygia
    recording  a specific performance / arrangement
```

Two gymnasts using "Spartacus" does not mean they used the same music: Mamun's
2014 hoop names the Adagio, Averina's 2018 hoop names only the ballet. When an
excerpt is not specified it is stored as *unknown*, never assumed equal to
another excerpt.
