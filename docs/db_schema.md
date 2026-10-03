# Planned database schema (SQLite)

Loaded only from the owner-reviewed layer (see CLAUDE.md, "Pipeline layers"). Names are
English snake_case; the diagrams render on GitHub.

## Core: what the current CSV files already contain

```mermaid
erDiagram
    country ||--o{ gymnast : "latest country"
    country ||--o{ championship_entry : "represented"
    gymnast ||--o{ gymnast_name : "spellings"
    gymnast ||--o{ championship_entry : "entered"
    event ||--o{ championship_entry : "has entries"
    gymnast ||--o{ routine : "performs"
    apparatus ||--o{ routine : "used in"
    event |o--o{ routine : "held at (optional)"
    routine ||--o{ track : "music of"

    country {
        text country_id PK "ISO alpha-3, or alpha-4 for former"
        text name "short name"
        text iso_name
        text alpha2
        text status "current / former / other"
        text valid_until "ISO 3166-3 withdrawal date"
    }
    gymnast {
        int gymnast_id PK
        text canonical_name "FIG > Wikipedia > table"
        text name_source
        text wiki_page
        int wikipedia_pageid
        text wikidata_id
        text fig_id
        text country_id FK "country of the latest championship"
        int first_year
        int last_year
    }
    gymnast_name {
        int gymnast_name_id PK
        int gymnast_id FK
        text name "one spelling seen in a source"
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
        text country_id FK "as written in that table"
        text nation_in_table
        text name_in_table
    }
    apparatus {
        int apparatus_id PK
        text name "Hoop Ball Clubs Ribbon Rope Gala"
    }
    routine {
        text routine_id PK "gymnast page, table, row"
        int gymnast_id FK
        int year
        int apparatus_id FK
        text variant "first / second / third"
        text context "gala, event note"
        text competition
        int event_id FK "nullable"
        text music_raw "cell as in Wikipedia"
        text parse_status
        text source_url
        int revid "article revision"
    }
    track {
        int track_id PK
        text routine_id FK
        int track_no
        text title
        text work_text "from ..."
        text artist_text "composer and by-credit"
        text performer_text
        text flags
        text status
        text raw_text
    }
```

## Planned: music entity resolution (work -> excerpt -> recording)

```mermaid
erDiagram
    artist ||--o{ work : "composes"
    work ||--o{ excerpt : "has parts"
    work |o--o{ track : "is"
    excerpt |o--o{ track : "is (if stated)"
    track ||--o{ track_credit : "credited"
    artist ||--o{ track_credit : "credited as"

    artist {
        int artist_id PK
        text name
        text kind "person / group / orchestra"
        text musicbrainz_id
    }
    work {
        int work_id PK
        text title "Spartacus (ballet)"
        int composer_id FK
        text musicbrainz_id
    }
    excerpt {
        int excerpt_id PK
        int work_id FK
        text title "Adagio of Spartacus and Phrygia"
    }
    track {
        int track_id PK
        int work_id FK "nullable until resolved"
        int excerpt_id FK "nullable: unknown stays unknown"
    }
    track_credit {
        int track_id FK
        int artist_id FK
        text role "composer / performer / unknown"
    }
```

## The two questions the schema answers

- gymnast -> music: `gymnast -> routine -> track`, filtered by `routine.year` and `apparatus`.
- music -> gymnasts: `work/excerpt -> track -> routine -> gymnast` (year, apparatus on the routine).
