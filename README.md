# rg-music-catalog

A searchable catalogue of the music used by rhythmic gymnasts in their routines, built from Wikipedia and MusicBrainz.

**Live site (EN/RU):** https://borisenkoanna1193.github.io/rg-music-catalog/

It answers two questions:

1. **Gymnast → music**: what did a gymnast perform to, by season and apparatus?
2. **Music → gymnasts**: who used a given piece, in which year, with which apparatus?

The second question is the hard part. The same music is written down in many ways across articles ("Carmen", "Carmen
Suite", "Habanera from Carmen", the same title for two unrelated songs), so the project is mostly data cleaning,
normalisation and entity resolution, not just downloading pages.

## What is in it

| | |
|---|---|
| Gymnasts | 1,395: everyone in the individual results of the World Championships 1963–2026; 196 with known music |
| Routines | 4,197 routine-years (a season "2022/2023" counts once per year) |
| Works | 2,595, with 2,948 versions (performers as the source credits them) |
| Sources | English Wikipedia (533 gymnast articles); Spanish Wikipedia adds 229 routines for 15 Spanish gymnasts; Russian Wikipedia 2 routines; MusicBrainz as evidence for matching |

## Pipeline

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export WIKI_CONTACT="https://github.com/<you>/rg-music-catalog"   # goes into the User-Agent

python -m rg_music.extract --seed data/seed_wc_gymnasts.txt   # English articles -> raw tables
python -m rg_music.native_wiki                                 # which home-language articles exist
python -m rg_music.pipeline --from native_extract --mb         # everything else, then tests
```

`rg_music.pipeline` runs the stages below, times them and compares the result with the last commit, so a change that
undoes an earlier decision fails the run instead of slipping through.

| Stage | Module | What it does |
|---|---|---|
| extract | `extract.py`, `wiki_client.py`, `tables.py` | MediaWiki API, 1 request/s, cache; every music table is expanded into a grid (rowspan/colspan) before columns are mapped by header |
| gymnast list | `worlds.py`, `countries.py`, `name_decisions.py` | names from 42 World Championships, one person per Wikipedia article, ISO country codes |
| native_extract | `native_extract.py` | music tables of the gymnast's home-language Wikipedia, apparatus and age categories translated |
| merge | `merge.py` | seasons into years; competition tables and home-language rows only fill gaps; conflicts are kept as flagged rows |
| parse | `parse.py`, `music_parser.py` | a music cell into tracks: title, work, artist, performer, with flags for every heuristic |
| works / resolve | `works.py` | tracks grouped into works; one title with unrelated credits stays split until there is evidence |
| mb_works | `mb_works.py` | MusicBrainz evidence: recording → work, credited writer |
| db, site_export | `db.py`, `site_export.py` | SQLite catalogue and the data of the static site (`site/app.html`) |

## Design choices

- **Raw data is never edited.** Every step writes new files; corrections live in `data/manual/*.csv`, keyed so that a
  rerun keeps them. Heuristic fixes are flagged in `notes` / `flags`, not applied silently.
- **A human decides the doubtful cases.** Ambiguous matches, translations and source conflicts go to a review sheet
  (Google Sheets); the decisions come back as CSV and are applied on every rebuild.
- **Same title is not the same work.** "Hello" by Adele and by Lionel Richie stay apart; covers join only with evidence
  (an alias decided by a person, a MusicBrainz link, or one classical composer).
- **Three levels of music:** work (Spartacus, Khachaturian) → excerpt (Adagio of Spartacus and Phrygia) → version (a
  performer). An excerpt that the source does not name is stored as unknown, never assumed.

The database schema is described in `docs/db_schema.md`. Tests: `python -m pytest -q` (fixtures mimic real table
layouts).

## Good to know

- Music is known only where an article lists it: so far for 196 of 1,395 gymnasts.
- Wikipedia has errors. Clear ones are corrected and noted in the data; some may remain.
- "Classical" follows the composer of a work, not the performer: a rock version of Vivaldi is still classical.
- When a source does not name the excerpt (only "Swan Lake", for example), the excerpt is unknown, never assumed.
- "Find on YouTube" opens a YouTube search; the site does not host or choose videos.

## Licences

Data from Wikipedia is CC BY-SA 4.0; MusicBrainz data is CC0.
