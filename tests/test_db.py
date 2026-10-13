import csv
import sqlite3

from rg_music.db import INTERIM, build


def test_the_catalogue_holds_every_routine_and_track_and_its_keys_hold():
    con = sqlite3.connect(":memory:")
    con.execute("PRAGMA foreign_keys = ON")
    counts = build(con)
    routines = list(csv.DictReader((INTERIM / "routines_parsed.csv").open(encoding="utf-8-sig")))
    assert counts["routine"] == len(routines)
    assert con.execute("PRAGMA foreign_key_check").fetchall() == []
    # every track with a work is linked to a version; Russian names fall back to empty, never to a wrong language
    unlinked = con.execute("SELECT COUNT(*) FROM track WHERE version_id IS NULL AND status NOT IN ('unknown', 'reference')").fetchone()[0]
    assert unlinked == 0
    assert con.execute("SELECT name_ru FROM work WHERE work_key = 'spartacus'").fetchone()[0] == "Спартак"
    assert con.execute("SELECT author_ru FROM work WHERE work_key = 'spartacus'").fetchone()[0] == "Арам Хачатурян"


def test_neutral_athletes_get_their_real_country_and_ain_is_never_a_country():
    con = sqlite3.connect(":memory:")
    build(con)
    rows = dict(con.execute("SELECT wiki_page, country_id FROM gymnast WHERE wiki_page IN "
                            "('Maria Borisova (gymnast)', 'Sofia Ilteriakova', 'Darya Viarenich')").fetchall())
    assert rows == {"Maria Borisova (gymnast)": "RUS", "Sofia Ilteriakova": "RUS", "Darya Viarenich": "BLR"}
    assert con.execute("SELECT COUNT(*) FROM gymnast WHERE country_id = 'AIN'").fetchone()[0] == 0
