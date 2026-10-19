# CLAUDE.md – context for working on rg-music-catalog

## What this is
A learning pet project for a portfolio (target role: Python data scraping engineer).
A catalog of music used by rhythmic gymnasts, built from English Wikipedia, answering:
1. gymnast → music (by season and apparatus);
2. music → which gymnasts used it, in which year, with which apparatus.

The owner talks in Russian; code, comments, README and commit messages are in English.

## Status (2026-10-19) — start here
- **MVP is published**: https://borisenkoanna1193.github.io/rg-music-catalog/ (public, GitHub Pages) and
  https://claude.ai/artifact/2Hz5iyZiwAmbv2N35ManNv (private). Repo https://github.com/BorisenkoAnna1193/rg-music-catalog,
  `main` in sync, 213 tests pass. 1,395 gymnasts (185 with music), 3,674 routines with music, 2,438 works, 2,772 versions.
- **Next session plan, pending owner actions and the proposed order: `docs/plan_next_session.md`.** Short version:
  PayPal Donate link → `SUPPORT_URL` in `site/app.html`; Spanish + Russian Wikipedia as a second source (translated to
  English); Russian names review; genres for "Other"; junior/senior split; group routines.
- The owner works in Russian, reviews tables in Google Sheets (Drive folder rg_music), not in CSV files.

## Current state (module by module; numbers as of each step)
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
  Last full run (2026-10-07): 3962 routines → 4075 tracks: 3487 routines ok, 176 partial, 11 manual, 2 unknown,
  286 with an empty music cell. "????" / "Unknown" mean unknown: a whole cell → kind `unknown` (no tracks), a title →
  track status `unknown`, a credit ("by ?") → empty artist, flags `unknown_credit` + `no_credit`.
- `rg_music/merge.py` – runs between extract and parse: expands seasons into one row per year and merges
  the competition tables into the routines → `routines_merged.csv`, `routine_events.csv` (many
  competitions per routine), `merge_report.json`. Pipeline: extract → merge → parse.
  Last run (2026-10-07): 3850 + 50 (season years) + 62 (new from competition tables) = 3962 routines; 167 competition
  rows merged as events, 2 real conflicts kept as separate rows (flag `differs_from_routine_table`).
  `data/manual/same_routine.csv` (owner): rows worded differently that are one routine (Godunko 2008 Rope Gopak/Hopak,
  Son Yeon-jae 2012 Ball Limelight/Chaplin), keyed by gymnast + year + apparatus + both music texts.
- `data/manual/music_overrides.csv` – tracks of cells the rules cannot split, typed/approved by the owner (keyed
  by the cell text, applied by `parse.py`, win over the rules, status `manual`). The 6 ambiguous cells are
  resolved this way: no `unparsed` tracks are left.
- `rg_music/works.py` – first pass of music matching → `data/interim/work_candidates.csv`: tracks grouped by a
  normalised TITLE (any script, ignores accents, "The", brackets, remix/instrumental words), with the distinct
  gymnast count and an `artist_check` (same_author / different_authors / no_credit). 2489 candidate works from
  4075 tracks; 422 are used by 2+ gymnasts (the only ones where matching matters); top: Boléro 13 gymnasts,
  Caravan 10, Feeling Good / Carmen / Caruso / I Put a Spell on You / Swan Lake 8, Malagueña / Smooth Criminal 7.
- Second pass (`python -m rg_music.works --resolve`) → `track_works.csv`, `works.csv`, `work_merge_review.csv`:
  owner aliases (`data/manual/work_aliases.csv`, e.g. every "O Fortuna" by Orff = Carmina Burana: O Fortuna),
  "Composer: Work" (composer_prefix), "Work: Excerpt" and "(from Work)" when that work is a track of its own
  (credits must overlap), spelling variants (0.95+, same numbers, 10+ chars, not a plural-only difference).
  2402 works (was 2489), 427 used by 2+ gymnasts. Top: Spartacus 16 gymnasts, Carmen (Bizet) 15, Swan Lake 14,
  Boléro 13, Caravan 10, Carmen Suite (Shchedrin) 9, Giselle 9, Feeling Good / Caruso / I Put a Spell on You 8,
  Carmina Burana 7 (15 routines). 130 tracks are assigned by the owner's aliases (Carmina Burana, Carmen, ballets).
  Then (2026-10-07) one title with credits that share no name is SPLIT into works `"<title> ~ <main credit>"` until there
  is evidence (owner alias; one classical composer and a non-generic title; MusicBrainz), and every track gets a
  version (work + performer as credited, minus the work's composer; spellings folded). Outputs `versions.csv`,
  `work_splits.csv` (per title: `split_by_credit`, `joined_by_musicbrainz` or `kept_classical_title`).
- `rg_music/mb_works.py` – MusicBrainz evidence for the split groups (by `split_key`, so reruns are stable):
  recording by that performer → its work; the credit names a writer of a work with that title (credited_author);
  second pass: the performer is among the recordings of that work (covers often lack the recording → work link).
  A name matches only if every word of the first credited name is in the MusicBrainz name (no first-name-only match).
  → `work_mb_links.csv`, `work_mb_proposals.csv`. `works.py --resolve` joins split groups with one MusicBrainz work,
  unless refused in `data/manual/work_mb_rejects.csv` (column `work_key`). **Order: works → works --resolve →
  mb_works → works --resolve.** Last run: 308 split groups, evidence for 144; 37 titles joined, 8 confirmed as
  different songs (Hello: Adele / Lionel Richie; Requiem; Main Title), 74 without evidence. Result: 2544 works,
  376 used by 2+ gymnasts, 2778 versions. MusicBrainz has duplicate works, so "apart" can be wrong (Toxic: 2WEI /
  Britney Spears).
  Owner checks by ear (2026-10-07), in `work_aliases.csv`: every Caravan = the jazz standard (Tizol / Ellington), every
  Libertango = Piazzolla, every Bésame Mucho = Velázquez (remixes too); Malagueña = two works: the song (Connie
  Francis, Caterina Valente, Brian Setzer for Verdeș 2017-18, performer found by ear) and Lecuona's piece (Stanley
  Black); Ave Maria = Schubert (Schubert, Vitas, 2WEI/Kallemaa) and "Vavilov/Caccini" (Libera, Wortley/Baldassarri;
  composed by Vladimir Vavilov, attributed to Caccini: the owner wants both names with a slash); "Caruso from Voice"
  by Neal Schon (Kapranova 2009 Ball) = Lucio Dalla's Caruso. Result: 2543 works, 376 used by 2+ gymnasts.
- `rg_music/work_review.py` – review sheet of the titles still split after MusicBrainz (one row per track, groups
  lettered A, B..., `decision` pre-filled with the own letter) → `work_split_review.csv`, uploaded to Google Sheets for
  the owner; `--import <sheet as csv>` → `data/manual/work_review_decisions.csv` (split_key → join_to + owner_note),
  applied by `works.py --resolve` after the MusicBrainz joins; a title that becomes one work gets the plain title key.
  Owner's review of 2026-10-10: all 101 titles checked, 104 decisions (most covers joined: Caruso, La Cumparsita,
  Kalinka, Hava Nagila...; kept apart e.g. Believer by Christina, Mission Impossible by Maxime Rodriguez, Hello,
  Requiem). Also: "Winter by Bond" (Charkashyna 2004) = Bond's "Wintersun" (Borisova hoop 2025-26); "I Will Never
  Forget You" / "Я тебя никогда не забуду" = one song, Rybnikov's romance from Juno and Avos (4 gymnasts);
  "Theme From Love Story" and Fiedler's "Love Story Theme" = Francis Lai's Love Story (7 gymnasts).
  Several cuts of one work by different performers in ONE routine are shown as one version, `version_type = medley`
  (owner: Onofriichuk 2026 Pump up the Jam = Bodybangers / Crazy Frog / Thomas Gold / Gabry Ponte).
  Result: 2439 works, 413 used by 2+ gymnasts, 2768 versions.
  Original performers recorded so far (for `version_type` original / cover in step 4): All By Myself = Eric Carmen
  (1975); Larry Dalton (Minagawa 2016-17) and Celine Dion (Santos 2023) are versions.
- `rg_music/work_authors.py` – step 4: author proposals for the 434 works used by 2+ gymnasts or classical without a
  composer → `work_author_proposals.csv`: MusicBrainz work (known link / credited writer / the only one with that title;
  "most recorded" is shown with "?" and never used), its type, lyrics (language zxx = no words, for the FIG rule),
  writers; proposal author_type folk / composer / performer / unknown by the owner's rules, `from_title` hint only when a
  cell says OST / film / musical... or MusicBrainz type is Soundtrack / Musical. First run: composer 119, performer
  147, folk 7, unknown 161. Review sheet `work_authors_review` in Drive (id `1ycH9XztMTMCqewczNgMVHkS0VCJGsDAU0dV-DxWQD_Q`,
  379 rows: classical with a known composer and owner-alias composers are not in it), rows map back by `row_id`.
  `--import <sheet csv>` → `data/manual/work_authors.csv` (434 works; owner 39 rows on 2026-10-12, proposal 340, rule 55):
  folk → author "folk music"; a name typed as author of a `performer` work, or "original: X" in owner_note, is the
  ORIGINAL performer; `data/manual/work_author_corrections.csv` (Claude's fixes with reasons: typos, film/TV/musical
  scores and tango → composer, old songs only used in a film → no from_title) is applied on top.
  `works.py --resolve` adds author_type / author / original_performer / from_title / from_type / has_lyrics /
  author_source to works.csv; a composer author makes a work classical when listed (Smetana, Rimsky-Korsakov:
  187 classical works); version_type original / cover from the original performer; FIG rule: a song with words
  (MusicBrainz) in a pre-2013 routine on an apparatus (not Gala) is an `instrumental` version of its own (43 tracks).
- `data/manual/routine_exclusions.csv` – routines the source states wrongly, dropped in `merge.py` (raw files keep
  them, `merge_report.json` lists them): Arina Averina 2020 Hoop (first) "Largo Al Factotum" (owner found no such
  routine). 3961 routines.
- `rg_music/classical.py` – `is_classical` (1/0) for every work in `works.csv`, plus `classical_basis` and
  `classical_composer`, for the dashboard filter and the share-by-year chart. Classical = the academic tradition
  (opera, ballet, concert music, old and 20th century); the flag follows the COMPOSER of the work, not the performer.
  Evidence in order: `data/manual/classical_overrides.csv` (owner) → composer (alias or any credited name) in
  `data/manual/classical_composers.csv` (89 names; ensembles named after a composer are skipped; a first name alone
  does not count) → composer at the start of a title ("Mendelssohn: Violin Concerto") → a STRONG form in a title
  (Op. N, Symphony, Piano Concerto, Sonata, Requiem, Act III) → default 0. 176 of 2406 works are classical (140 by
  composer, 14 by composer in title, 22 by title form). Share of routines with a classical track: 31% in 1990-94,
  13% in 2015-19, 8% in 2020-24, 4% since 2025. Boundaries CONFIRMED by the owner (2026-10): not classical = Piazzolla/tango, Lecuona (Malagueña), Einaudi, film
  composers, folk (Kalinka, Hopak), Mrvica's own pieces; classical = Gershwin, operetta, rock/cross-over arrangements
  of classical pieces (Vivaldi Storm, Albinoni in Rock, Moonlight Rumba). Three doubtful flags (Sholay sitar concerto,
  Trans-Siberian Orchestra overture, Bellini Portreyi Yaparken) are left as they are for the MVP.
- `rg_music/composers.py` – composer SUGGESTIONS from MusicBrainz for works with 3+ gymnasts →
  `composer_suggestions.csv` (high 37 / probable 44 / ambiguous 48 / none 17 of 146); never applied automatically.
  Checked on the top 16: right for Boléro, Caravan, Feeling Good, Caruso, I Put a Spell on You, Malagueña,
  Smooth Criminal, Summertime, Besame Mucho; wrong or doubtful for Spartacus (Alex North), Swan Lake, Giselle,
  Don Quixote ("probable" gave Cervantes, the novel's author): ballets are not reliable there.
- `rg_music/llm_parse.py` – LLM fallback (OpenRouter, strict JSON schema, Pydantic, verbatim check, cache),
  built and tested with a fake transport but **not used**: for 6 cells manual overrides were cheaper than an API
  key + setup (owner's call). Keep it for jobs with many cells (190 tracks without credit, 18 prose-only pages,
  classical-name proposals). Needs `OPENROUTER_API_KEY` (env or git-ignored `.env`); `--dry-run` shows the request.
- Russian names: `data/reference/apparatus.csv`, `name_ru` in `data/reference/countries.csv`,
  `rg_music/names_ru.py` → `data/interim/gymnast_names_ru.csv` (163 of 533 from Wikidata; empty = show Latin).
- Seed: `data/seed_gymnasts.txt` (10 Olympic AA medalists 2008–2024).
  `data/seed_wc_gymnasts.txt` = the 533 gymnasts with an article (from `wc_gymnasts_final.csv`);
  run with `--seed`. Last full run: 533 pages OK, 173 with a routine table, 3850 routine rows;
  crosscheck on 241 competition rows: 136 match / 10 fuzzy / 3 year-shifted / 21 differ / 71 no routine table.
- Tests: `python -m pytest -q` (fixtures mimic real layouts).

## Documentation map
- `docs/db_schema.md` – SQLite schema (ER diagrams, Mermaid; the MVP tables are built by `rg_music/db.py`).
- `docs/pipeline.md` – the process as it went: steps 1–18 in order, forks, owner decisions, the scripts behind each step,
  and the full rebuild order.
- `docs/plan_next_session.md` – where we stopped, what waits for the owner, the proposed order of the next tasks.
- `docs/case_decisions.txt` – decisions in Step / substep / action / result / tech / file_names form (portfolio case).

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

## Decisions after the full run (made with the owner)
- **A season "2022/2023" = the same music in both years**: expanded into one routine row per year that
  differ only by the year (id `...#2022`, `...#2023`, `year_source` keeps the text, flag `expanded_from_season`).
- **"Same music" = same work, key = title + composer/artist** (not the title alone, not the recording).
  Different excerpts of one work are normal.
- **Competition tables are merged into routines**: same gymnast + apparatus + year (±1) + similar music
  (whole text, or a track title / work name, or one title inside the other) = the same routine; the
  competition becomes a `routine_events` row. No match = new routine with `source=competition_table`
  (Kabaeva-style pages); different music in the same year = new row flagged, never overwritten.
  One routine can have several events (badge "performed at World Championships").
- **Bilingual (EN+RU), done now**: apparatus and countries (reference files), gymnast names from Wikidata
  with Latin fallback. **Postponed**: classical works/composers (needs `work`/`artist` tables).

- **Same title is not always the same work; the credit decides** (`data/manual/work_aliases.csv`, optional
  `work_key` column). Bizet's opera *Carmen* and Shchedrin's ballet *Carmen Suite* stay SEPARATE works
  (credits naming Shchedrin come first in the file because they often name Bizet too); Stromae's "Carmen" is another
  song (`carmen stromae`); "Carmen's Story" (Piaf), "Donna Carmen", "La Habanera" (Yello) are other music;
  "Carmen Fantasie/Fantasia" (violin) stays separate by default. The six "Carmen" tracks whose author is
  not Bizet (Arcadian, Antonio de Lucena, Michelle Minke/James Noble, Marcin Patrzalek, "Marcin", none for Zhao
  Yating) are kept in Carmen with the authors as credited (composer unverified).
- **Ballet excerpts** (owner, 2026-10): "Adagio" by Khachaturian = Adagio of Spartacus and Phrygia; Bessonova's 2002-2004
  hoop medley (Molto Meno Mosso / Allegro-Valse-Allegro-Vivo / Finale / Alla Breve-Moderato e Maestoso / Moderato) =
  Swan Lake; Son Yeon-jae "Pas de Deux" (2011-2012) = The Nutcracker; Averina 2015 "Giselle, Act I: No. 8, Waltz" is
  credited to Tchaikovsky in the source but is Adam's Giselle (source error, corrected in the alias note). Sabre Dance and
  Gopak = Gayaneh, Mazurka and Waltz = Masquerade; Amirov's "One Thousand and One Nights" is not Scheherazade;
  Bond's "Quixote" is not Don Quixote.
- Melitina Staniouta 2014 "Obsession (On Theme K. Orff. Carmina Burana)" is a separate work (arrangement).
- Limelight (owner, 2026-10-07): "Terry's Theme", "The Terry Theme From Limelight", "Limelight (Main Theme)",
  "Limelight Theme" = one work, Chaplin's theme from the film (key `limelight chaplin`, 5 gymnasts); Billy Vaughn,
  André Rieu etc. are versions.

## Decisions for the `work` table (owner, 2026-10-07; implemented 2026-10-12)
- Fields: `name_en`, `name_ru`, `author_en`, `author_ru`, `author_type` (`composer` / `performer` / `folk` /
  `unknown`), `author_source` (owner / rule / musicbrainz / credit). Empty `name_ru`/`author_ru` = show the English one.
  The performer of a given routine stays on the track, not on the work. `author_type` also drives checks (a
  `performer` work whose author no track credits = probably different songs merged).
- Author by kind: classical = composer; jazz standards and tango = composer; folk = "folk music" / "народная музыка"
  (`folk`); pop song = performer (on the `version`, see below), NOT the songwriters from MusicBrainz; if the original and the best-known performer
  differ, take the one the gymnasts perform to (I Will Always Love You = Whitney Houston). Song written for a film
  (composer and singer differ, My Heart Will Go On) = who sings: people search by the singer they heard.
- **Versions are not merged** (owner, 2026-10-07): the performer is kept as the source states it (David Garrett and
  Michael Jackson for Smooth Criminal; Muse and Bublé for Feeling Good). Dashboard idea: pick "Feeling Good" →
  branches per performer → who used that version and when.
- **Two levels: `work` → `version` → `track`** (owner, 2026-10-07). `version` = work + performer exactly as credited,
  with `version_type` (original / cover / remix / arrangement / cast / unknown); no separate "creator" field
  (musical composer = `work.author`, singers/remixer = `version.performer`). Pop works show NO author in the header,
  only the version branches (so `author` on a pop `work` is empty; label in lists = title + main performer).
  Classical credited only to the composer → version performer `unknown` (the composer never counts as a performer).
- **Same title + different performers = different works until there is evidence**: owner alias → MusicBrainz
  recording→work link → original author named in the cell → classical: same composer. No evidence = kept apart.
- **`from_title` + `from_type`** (film / musical / series / game) on `work`, ONLY for music written for it
  (Skyfall, The Mask of Zorro, Chicago, Titanic → My Heart Will Go On). Old songs that merely appear in a film
  (Caravan in Ocean's 13, Bella Ciao in Money Heist, Paint It Black in Wednesday) do not count for the film ranking.
- Dashboard rankings: top performers (`version.performer`), top composers (`work.author` where `author_type =
  composer`), top films (`work.from_title`).
- Russian names: classical AND folk titles are translated (Gopak → Гопак); pop titles and performers are not.
- **Folk** (owner, 2026-10-12) = not only music written by the people but folk motifs, paso doble, Spanish music
  (La Zarzamora: folk, Paco de Lucía is the performer).
- **from_title, owner's exception (2026-10-12):** when a piece was written for a series / musical but is known from a
  film, show the better-known source: Green Hornet → Kill Bill, Mission: Impossible → film, Chicago → film. Only one
  source per work (two would complicate the film ranking). No "performance" type (Cirque du Soleil shows).
- Misirlou = Miserlou (Caroline Campbell & William Joseph is the Pulp Fiction cover; David Garrett): one work,
  original = Dick Dale (the best-known version).
- English spelling for the Ukrainian folk dance: "Gopak" (gopak / hopak / hopak ukrainian folk = one folk work;
  Khachaturian's Gopak stays in Gayaneh).
- "Storm": Otyken, Havasi and Burkard Dalwitz are separate works (Otyken is unrelated to Vivaldi).
- Kanaeva 2008 Clubs "LA Lights" "(same music as CariPrato 2007)" → expand to "Song #1" by Serebro (with a note).
- A cell that says the music is unknown ("????", Bezzoubenko) → no track title, status `unknown`.

## FIG rule on music with words (owner, 2026-10-08; implemented 2026-10-12 as instrumental versions)
- Before 2013 no music with words; 2013-2016 words allowed in 1 of the 4 routines of a season; 2017-2021 in 2 of 4;
  from 2022 no limit. So a pop song in a pre-2013 routine was an instrumental / remix / vocalise version even when the
  source credits the original singer ("Feeling Good by Muse", Nazarenkova 2012).
- Use: same WORK (Nazarenkova 2012 and Kolosov 2023 are both Feeling Good), but a different VERSION: pre-2013 pop
  versions get `version_type = instrumental` with a basis "inferred from the FIG rule". Implement together with the
  owner's work_split_review decisions.
- Not now (owner): a report of routines that break the rule (vocal pre-2013, too many vocal routines in a season).
- Vocalises without words were allowed before 2013 (Caravan by Antonella Ruggiero is fine); Gala / exhibition routines
  are outside the rule, words allowed there (owner, 2026-10-12, "as far as I remember").
- Videos (later): search for the video of the gymnast's performance, not for the music on YouTube.

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
- AIN is never a country (owner, 2026-10-13): gymnasts who competed only as AIN get their real country from
  `data/manual/gymnast_country_overrides.csv` (Maria Borisova, Sofia Ilteriakova → RUS; Darya Viarenich → BLR), applied
  in `db.py`; without an override the country stays empty.
- Owner-typed cells in `wc_name_review_fig.csv` (empty `decision_basis`) are never overwritten.
- CSVs the owner opens in Excel are written as utf-8-sig (BOM), otherwise Excel garbles diacritics.
- **Owner review sheets live in Google Drive**, folder `rg_music` (id `1HOkycl3RAW9tFOP0Z5_-uhVUE0t2JLET`): the owner
  cannot edit CSVs comfortably. A sheet is uploaded through the Drive connector (CSV → Google Sheet; no Sheets editor
  connector, so no formatting), checked by exporting it back as CSV, and decisions are read back the same way.
  `work_split_review` (id `1TnTbY10EPqylQ5OrtdXxnR_PGScr4y4EDNlv4s71Bfc`) = `python -m rg_music.work_review` without the
  technical columns; rows map back by `row_id` to `data/interim/work_split_review.csv`.
- Result: `data/interim/wc_gymnasts_final.csv` (1395 people, each with `country_id`).

## Next
Owner's additions (2026-10-13):
- **Junior / senior periods.** Split a gymnast's routines into junior and senior seasons and let every music statistic
  (rankings, classical share, music lists) filter by it. Possible evidence: birth year (Wikidata P569) against the FIG
  age limit of that period (the limits changed over the years: check them), and labels in the source ("(Individual
  júnior)" in the Spanish tables, "Junior" in English ones). To decide with the owner: the age rule per period.
- **Group routines.** A catalogue of group exercises: no gymnast names, the team = country + year + apparatus
  combination (5 hoops, 3 ribbons + 2 balls...) + music; members optional. The owner is looking for a source with group
  music. Schema idea: `group_routine(country_id, year, apparatus_combo, music...)` sharing work / version / track.
- YouTube stage 2 postponed (owner): search links only for now.

Open work (details and order in `docs/plan_next_session.md`):
1. Home-language Wikipedia as a second source: Spanish (12 gymnasts) and Russian (Kabaeva) tables, translated to
   English, merged by the competition-table rule (English first, conflicts flagged).
2. Russian names: owner review of the 55 works / 61 composers Claude translated, then the rest of classical and folk.
3. 122 popular works with an unknown author (sheet `work_authors_review`), genres for "Other" (jazz, tango, film).
4. Junior / senior split; group routines (above).
5. Later: rgforum.no archive (check ToS/robots, 1 req/s), YouTube stage 2, typo-tolerant search on the site,
   23 pairs in `work_merge_review.csv` (short titles, roman numerals), Russian Wikipedia for ex-USSR gymnasts.
Done since the plan was first written: ballet families, work/version model, MusicBrainz evidence, owner reviews,
authors, SQLite, the site.

Known source errors worth catching in validation: Averina 2015 "Giselle" attributed to
Tchaikovsky (it is Adam); "Mvrica" (Mrvica); Kudryavtseva 2016 ball "from Toy Story 4"
only in one of two tables; Kanaeva 2012 "Fantasie Impromptu No 66" (Op. 66).

## Findings from the full run on 533 gymnast pages (new tasks)
- **Coverage is the main limit**: only 173 of 533 articles have a music table. 323 are stubs with no
  mention of music (median 3 KB), 18 mention music only in prose, 16 have music only in a
  *competition* table (68 rows not yet in `routines_parsed`). → competition rows are merged (done); the rgforum.no archive is justified as an additional source; prose could go to the LLM.
- **Seasons instead of years** (45 rows, 10 pages): resolved, expanded per year (see decisions).
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
- **Source conflicts exist**: 4 competition rows (2 after the owner's same_routine.csv) (after title-based matching) contradict the routine table
  (e.g. Vitrychenko 2000: "Pink Dream" vs "Apassionata"; Zhukova 2008): kept as separate flagged rows;
  needs a validation report, not silent resolution.

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

## MVP (2026-10-13)
- `rg_music/db.py` → `data/catalog.sqlite` (git-ignored, rebuilt from the CSV layers; FK-checked): country, apparatus,
  gymnast, routine, routine_event, work (+ name_ru, author_ru, author_type, from_title, has_lyrics), version, excerpt,
  track. Russian names: `data/manual/work_names_ru.csv` (55 works) and `composer_names_ru.csv` (61 composers), only the
  ones Claude is sure of (source `claude`); the owner reviews and completes them later.
- `rg_music/site_export.py` → `site/data.json` (compact, references by list position, ~460 KB) and `site/index.html`
  (= `site/app.html` wrapped into a full document). `site/app.html` is the whole static site (vanilla JS, hash routes
  #home #gymnasts #gymnast-N #music #work-N #rankings, EN/RU, light only like the mockups, both ranking modes); it computes every
  statistic in the browser. Pipeline end: `python -m rg_music.db && python -m rg_music.site_export`.
- Published: claude.ai artifact https://claude.ai/artifact/2Hz5iyZiwAmbv2N35ManNv (republish `site/app.html` with
  files {"data.json": "site/data.json"}) and GitHub Pages https://borisenkoanna1193.github.io/rg-music-catalog/
  (repo https://github.com/BorisenkoAnna1193/rg-music-catalog, public; `.github/workflows/pages.yml` redeploys on every
  push to main that changes site/; Pages source = GitHub Actions).
- Git: commits use the GitHub noreply address 152020947+BorisenkoAnna1193@users.noreply.github.com (history rewritten
  before the first push; the old history is only in the local branch `backup-before-email-rewrite`, never pushed).
  Pushing uses the passphrase-free key ~/.ssh/id_ed25519_github (~/.ssh/config, Host github.com).

## Second language of Wikipedia (probe 2026-10-13, not integrated yet)
- `rg_music/native_wiki.py` probes the gymnast's home-language Wikipedia (+ Russian for ex-USSR) for music tables →
  `data/interim/native_wiki_probe.csv`. Result: 297 of 533 have a home-language article, 25 with a music table;
  15 gymnasts would get music for the first time (+~190 rows; 12 Spanish: Almudena Cid 55, Jennifer Colino 26,
  Esther Domínguez 21...; Alina Kabaeva from ru; Shin Soo-ji from ko), 6 more seasons elsewhere. Other languages add
  almost nothing.
- Plan (owner agreed in principle): English first, home language only fills missing routines (same rule as the
  competition-table merge), conflicts kept as flagged rows. **Spanish content must be translated to English** (the
  site is EN/RU): titles and credit words ("de", "compuesto por"), apparatus (Aro, Pelota, Mazas, Cinta, Cuerda).
- WikiClient now takes `lang` (cache in data/raw/<lang>/) and has `langlinks()`; cache keys of non-ASCII titles carry
  a hash (they used to collide: every Cyrillic title was one file).

## Dashboard decisions (owner, 2026-10-13)
- Style: direction **D · Apparatus** (Manrope, rounded cards, pill tabs, one colour per apparatus: hoop #2F5BEA, ball
  #E8833A, clubs #0E9F8E, ribbon #B24BD6, rope #8A8D96). Mockups: claude.ai artifact
  https://claude.ai/artifact/PfpVE3fW8DyDnPuQNZm2Kv (pages "D · Apparatus — EN" / "— RU"; EN/RU switch on every screen).
- Tabs: Home, Gymnasts, Gymnast page, Music, Work page, Rankings (music, performers, composers, films).
- **All gymnasts are shown** (owner, 2026-10-13): all 1395 World Championship gymnasts are in the database and on the
  site; without known music a card / page shows country, World Championship years and "music not known yet" (with or
  without a Wikipedia article). Filter "Only with known music" is off by default.
- Rankings count **both** by gymnasts and by routines (switch). Routines = every routine row: the same music on another
  apparatus or in the next season counts again ("how often it was heard"); Carmen leads by routines (22), Spartacus
  by gymnasts (16).
- RU: UI, countries, apparatus, classical + folk titles and composers translated; pop titles, performers, films stay;
  gymnasts without a Russian name are shown in Latin.

## Ideas and open questions (not decided yet)
- **Genres instead of classical / not classical**: after the MVP, extend `is_classical` to a genre (classical / folk /
  film music / pop / rock / jazz / tango ...), probably a `genre` column on `work` with the same evidence-and-basis
  approach and an owner override file; the share-by-year chart would then show every genre.
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
- **YouTube, stage 1 done (2026-10-13):** every routine has "Find on YouTube": a YouTube search URL built in the page
  (gymnast, apparatus, season, short music title; Russian query on the Russian page). Nothing is fetched from YouTube.
  Stage 2 (optional): candidates from the YouTube Data API (key + ~100 searches/day free), verified by the owner,
  shown as "Watch". Scraping YouTube search is against its terms: not done.
- **YouTube links** under each music result: the video of that gymnast's performance, year and
  apparatus must match. Schema idea: `video_link(video_id, routine_id, url, source, verified)`;
  automatic search results (YouTube Data API: key + quota, check its terms) are only candidates
  until verified; link out rather than embed.

## Later steps
Entity resolution (same music across gymnasts, composer vs. performer) (rapidfuzz + MusicBrainz + LLM arbiter), validation
(years vs. career from Wikidata, apparatus vocabulary), Wikidata as second source for
gymnast list, exports (CSV/JSON/Google Sheets/SQLite),
search UI, Docker + scheduled run + S3.
