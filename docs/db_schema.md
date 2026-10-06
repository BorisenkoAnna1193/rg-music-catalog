# Planned database schema (SQLite)

Loaded only from the owner-reviewed layer (see CLAUDE.md, "Pipeline layers"). Names are English snake_case; the diagrams
render on GitHub. Counts are from the last run. Russian names (`name_ru`) are empty when unknown; the UI falls back to Latin.

## Core: gymnasts, routines, events (data exists in the CSV files)

```mermaid
erDiagram
    country ||--o{ gymnast : "latest country"
    country ||--o{ championship_entry : "represented"
    gymnast ||--o{ gymnast_name : "spellings"
    gymnast ||--o{ championship_entry : "entered"
    event ||--o{ championship_entry : "has entries"
    gymnast ||--o{ routine : "performs"
    apparatus ||--o{ routine : "used in"
    routine ||--o{ routine_event : "performed at"
    event |o--o{ routine_event : "known championship (optional)"
    routine ||--o{ track : "music of"

    country {
        text country_id PK "ISO alpha-3, alpha-4 if former"
        text name "short name"
        text name_ru "short Russian name"
        text iso_name
        text alpha2
        text status "current / former / other"
        text valid_until "ISO 3166-3 withdrawal"
    }
    gymnast {
        int gymnast_id PK
        text canonical_name "FIG > Wikipedia > table"
        text name_ru "Wikidata, empty if unknown"
        text name_source
        text wiki_page
        int wikipedia_pageid
        text wikidata_id
        text fig_id
        text country_id FK "latest championship"
        int first_year
        int last_year
    }
    gymnast_name {
        int gymnast_name_id PK
        int gymnast_id FK
        text name "one spelling seen"
        text source "wc_table / wikipedia / fig"
    }
    event {
        int event_id PK
        text name "World Championships"
        int year "year actually held"
        text city
    }
    championship_entry {
        int entry_id PK
        int gymnast_id FK
        int event_id FK
        text stage "qualification / all-around"
        text country_id FK "as in that table"
        text nation_in_table
        text name_in_table
    }
    apparatus {
        int apparatus_id PK
        text name "Hoop Ball Clubs Ribbon Rope Gala Free hands"
        text name_ru "Обруч Мяч Булавы ..."
    }
    routine {
        text routine_id PK "page, table, row (+ #year if a season)"
        int gymnast_id FK
        int year "one row per year of a season"
        text year_source "2022/2023 if expanded"
        int apparatus_id FK
        text variant "first / second / third"
        text context "gala, event note"
        text music_raw "cell as in Wikipedia"
        text parse_status
        text source "routine_table / competition_table / both"
        text source_url
        int revid "article revision"
    }
    routine_event {
        int routine_event_id PK
        text routine_id FK
        text competition "as in the competition table"
        text location
        int event_year "year the event was held"
        int event_id FK "nullable"
    }
    track {
        int track_id PK
        text routine_id FK
        int track_no
        text title
        text artist_text "composer and by-credit"
        text performer_text
        int work_id FK "see the music diagram"
        int excerpt_id FK "nullable"
        text match_method "alias / colon_prefix / from_work / title ..."
        text status "ok / partial / manual / reference"
        text flags
        text raw_text
    }
```

## Music: works, excerpts and the classical flag (built; artists planned)

`work` and `excerpt` come from `works.csv` / `track_works.csv` (2 406 works, 75 excerpts). `artist` and `track_credit`
are planned: today the credit stays text in `track.artist_text`.

```mermaid
erDiagram
    work ||--o{ excerpt : "has parts"
    work ||--o{ track : "is"
    excerpt |o--o{ track : "is (if stated)"
    artist |o--o{ work : "composes"
    track ||--o{ track_credit : "credited (planned)"
    artist ||--o{ track_credit : "credited as (planned)"

    work {
        int work_id PK
        text work_key UK "normalised title, or an explicit key"
        text title "Spartacus"
        text composer "from the owner rules, else empty"
        int is_classical "1 classical, 0 not"
        text classical_basis "manual / composer / composer_in_title / title_keyword / default"
        text classical_composer "composer that made it classical"
    }
    excerpt {
        int excerpt_id PK
        int work_id FK
        text title "Adagio of Spartacus and Phrygia"
    }
    track {
        int track_id PK
        int work_id FK
        int excerpt_id FK "nullable: unknown stays unknown"
    }
    artist {
        int artist_id PK
        text name
        text kind "person / group / orchestra"
        text musicbrainz_id
    }
    track_credit {
        int track_id FK
        int artist_id FK
        text role "composer / performer / unknown"
    }
```

## The two questions the schema answers

- gymnast -> music: `gymnast -> routine -> track -> work`, filtered by `routine.year` and `apparatus`.
- music -> gymnasts: `work (excerpt) -> track -> routine -> gymnast`; "classical or not" and its share by year come from
  `work.is_classical` joined to `routine.year`.
