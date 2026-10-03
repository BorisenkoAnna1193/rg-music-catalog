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
  Last full run: 3850 routines → 3943 tracks: 3731 ok, 204 partial, 7 unparsed (ambiguous splits, for the
  LLM), 1 reference; 286 routines have an empty music cell. `year_from`/`year_to` handle seasons ("2022/2023").
- Seed: `data/seed_gymnasts.txt` (10 Olympic AA medalists 2008–2024).
  `data/seed_wc_gymnasts.txt` = the 533 gymnasts with an article (from `wc_gymnasts_final.csv`);
  run with `--seed`. Last full run: 533 pages OK, 173 with a routine table, 3850 routine rows;
  crosscheck on 241 competition rows: 136 match / 10 fuzzy / 3 year-shifted / 21 differ / 71 no routine table.
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

## Decisions for the gymnast list (made with the owner)
- List of gymnasts = names in individual qualification + individual all-around tables of all
  World Championships (`rg_music/worlds.py`); identity = Wikipedia article (via redirects).
- Canonical name hierarchy: FIG name (surname as "Aaaa", "Given Surname") → Wikipedia article
  title → most frequent/latest table spelling (`rg_music/name_decisions.py`). FIG ids come from
  Wikidata (P2696/P7440) and only for gymnasts in the review sheet (`rg_music/fig_names.py`).
- **Country reference** (`rg_music/countries.py`, `data/reference/`): ISO 3166-1 + ISO 3166-3
  (via pycountry) + aliases (IOC codes, "West Germany" → Germany, "Korea" → South Korea, ...).
  `country_id` = alpha-3 (current) / alpha-4 (former: SUHH, CSHH, DDDE, YUCS). Free-text countries
  are matched code → exact → name inside text → most similar (difflib, cutoff 0.84) → none; the
  method is stored (`wc_country_mapping.csv`) and everything but code/exact is for review.
  Years are ignored ("Czech Republic" in 1971 stays CZE); year-vs-existence is not validated yet.
- Same person under two countries (successor states): country = latest championship; entries that
  are not countries (Individual Neutral Athletes) are skipped when choosing it.
- Owner-typed cells in `wc_name_review_fig.csv` (empty `decision_basis`) are never overwritten.
- CSVs the owner opens in Excel are written as utf-8-sig (BOM), otherwise Excel garbles diacritics.
- Result: `data/interim/wc_gymnasts_final.csv` (1395 people, each with `country_id`).

## Next
1. Owner review of `tracks.csv` + `overrides.csv` mechanism.
2. Second source: rgforum.no music list (archived on Wayback, last snapshot ~2022; the
   live site does not resolve). Check ToS/robots, 1 req/s; use it to cross-check Wikipedia
   and to enrich `no_credit` tracks. LLM fallback only if rules prove insufficient.
3. SQLite schema + loader.

Known source errors worth catching in validation: Averina 2015 "Giselle" attributed to
Tchaikovsky (it is Adam); "Mvrica" (Mrvica); Kudryavtseva 2016 ball "from Toy Story 4"
only in one of two tables; Kanaeva 2012 "Fantasie Impromptu No 66" (Op. 66).

## Findings from the full run on 533 gymnast pages (new tasks)
- **Coverage is the main limit**: only 173 of 533 articles have a music table. 323 are stubs with no
  mention of music (median 3 KB), 18 mention music only in prose, 16 have music only in a
  *competition* table (68 rows not yet in `routines_parsed`). → merge competition rows as a second
  source; the rgforum.no archive is justified as an additional source; prose could go to the LLM.
- **Seasons instead of years** (45 rows, 10 pages: "2022/2023", "2017-18", "2010-2012").
  `year_from`/`year_to` added; open: model as a range in the DB or pick one year.
- **Music matching** (3939 tracks, 2491 distinct normalised titles, 865 titles used 2+ times):
  - ASCII-folding makes titles in Cyrillic/Korean/etc. empty (53 tracks): need a Unicode-aware key.
  - Same title, different performers (Caruso: 4, Feeling Good: 4+). **Decided: "same music" = same
    work**, not same recording; different excerpts of one work (Swan Lake, Don Quixote) are
    normal and shown as detail. Risk to handle: one title can be different songs ("Hurt"), so the
    work key needs the composer/MusicBrainz, not the title alone. Artist spellings also vary
    ("Cagey String"/"Cagey Strings", "Glee cast"/"Kenny Loggins").
  - 158 tracks look classical (Op., No., Symphony...): work/excerpt/composer split is needed there.
- **Parser**: titles containing "by" ("Paris By Night", "Stand by Me") are handled (flag `by_in_title`);
  ambiguous "A by X, B and C by Y" splits are NOT guessed (7 cells left unparsed for the LLM);
  181 tracks have no credit (enrich from another source).
- **Source conflicts exist**: 21 competition rows contradict the routine table (e.g. Vitrychenko 2000:
  "Pink Dream" vs "Marche en la ..."): needs a validation report, not silent resolution.

## Bilingual dashboard (EN + RU): plan and estimates
Decided to offer English and Russian. What gets a Russian version:
- **UI strings**: trivial (i18n dictionary).
- **apparatus**: a `name_ru` column in the `apparatus` table (7 values); no separate reference.
- **countries**: ISO translations in pycountry cover 278 of 281 entries, but as long official forms
  ("Российская Федерация", "Республика Корея", "Китайская провинция Тайвань"): add ~20 short-name
  overrides (Россия, Южная Корея, Китайский Тайбэй, СССР...); about an hour. Turkey, Yugoslavia missing.
- **gymnast names**: Wikidata has a Cyrillic label for 163 of the 533 articles (30%): 70-95% for
  Russia/USSR/Belarus/Ukraine/Bulgaria, ~20-30% elsewhere; none for the 877 gymnasts without an
  article. Labels need cleaning ("Солдатова, Александра Сергеевна" -> "Александра Солдатова").
  Plan: `gymnast.name_ru` nullable, fall back to the Latin name; search works on both.
  Transliteration for the rest is optional and only reliable for Slavic names (Chinese/Spanish no).
- **classical titles and composers (not started; estimate before deciding)**: ~330 tracks (8%)
  look classical, ~200 distinct titles, a few dozen composers (the credits are dominated by about
  20: Tchaikovsky, Bizet, Stravinsky, Khachaturian, Ravel...). Fully automatic lookup is unreliable:
  Wikidata search finds "Лебединое озеро" and "Пётр Ильич Чайковский" but also returns an insect
  genus for "Spartacus", the novel for "Don Quixote" and a given name for "Carmen". Proposed
  criteria: translate only works/composers on a **reviewed whitelist** (classical, ballet, opera,
  traditional Russian titles), proposals from Wikidata + owner review; never translate pop/rock
  titles or performers (1872 distinct artist strings); keep Cyrillic song titles as written.
  Effort about 1-1.5 days, after the `work`/`artist` tables exist (translation belongs on those
  entities as `name_ru`, not on raw text).

## Ideas and open questions (not decided yet)
Dashboard for browsing the DB (decide `event` and filters after the first version is drawn):
- Search/filters: gymnast name, country, year; **apparatus as a filter** is probably convenient
  (owner leaning yes). Result = the gymnast(s), then their music.
- **`event` as a badge, not (only) a filter.** Within one year a gymnast can have several music
  pieces for the same apparatus (e.g. Taisiia Onofriichuk 2026: one ribbon music early in the
  season, then Carmen). Where the source states the competition, show next to the title and
  artist a badge such as "performed at World Championships 2026". Where it does not, no badge:
  `championship_entry` only says the gymnast competed, not with which music or apparatus, so the
  badge must come from `routine.event_id` (filled from the "competition" column / competition
  tables), never inferred from the year alone. This is the use case for the optional `event_id`.
- **YouTube links** under each music result: the video of that gymnast's performance, year and
  apparatus must match. Schema idea: `video_link(video_id, routine_id, url, source, verified)`;
  automatic search results (YouTube Data API: key + quota, check its terms) are only candidates
  until verified; link out rather than embed.

## Later steps
Entity resolution (same music across gymnasts, composer vs. performer) (rapidfuzz + MusicBrainz + LLM arbiter), validation
(years vs. career from Wikidata, apparatus vocabulary), Wikidata as second source for
gymnast list, exports (CSV/JSON/Google Sheets/SQLite),
search UI, Docker + scheduled run + S3.
