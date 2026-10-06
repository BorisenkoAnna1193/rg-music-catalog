import pytest

from rg_music.works import artist_check, build_candidates, name_tokens, title_key


@pytest.mark.parametrize("a, b", [
    ("Boléro", "Bolero"),
    ("The Pink Panther Theme", "Pink Panther Theme"),
    ("Romani Holiday (Antonius Remix)", "Romani Holiday"),
    ("Smooth Criminal (Instrumental)", "SMOOTH CRIMINAL"),
    ("Mercy - Remix", "Mercy"),
    ("Lay All Your Love On Me (from Mamma Mia!)", "Lay All Your Love On Me"),
])
def test_same_work_gets_the_same_key(a, b):
    assert title_key(a) == title_key(b)


def test_different_titles_and_other_scripts():
    assert title_key("Swan Lake") != title_key("Sleeping Beauty")
    assert title_key("Двигаться") == "двигаться"  # not emptied by an ASCII fold
    assert title_key("특(S-Class)") == "특"
    assert title_key("") == ""


def test_name_tokens_ignore_generic_words_and_accents():
    assert name_tokens("Pyotr Ilyich Tchaikovsky") == {"pyotr", "ilyich", "tchaikovsky"}
    assert name_tokens("Smolensk Symphonic Orchestra and Choir") == {"smolensk", "symphonic"}
    assert "bublé" not in name_tokens("Michael Bublé") and "buble" in name_tokens("Michael Bublé")


def test_artist_check():
    assert artist_check(["Pyotr Ilyich Tchaikovsky", "Tchaikovsky", "Pyotr Tchaikovsky"]) == "same_author"
    assert artist_check(["Luciano Pavarotti", "Lara Fabian"]) == "different_authors"
    assert artist_check(["", ""]) == "no_credit"
    assert artist_check(["Queen"]) == "same_author"


def _track(rid, title, artist):
    return {"routine_id": rid, "title": title, "artist": artist}


def _routine(page, year):
    return {"gymnast_page": page, "year": str(year)}


def test_popularity_counts_distinct_gymnasts_not_routines_or_seasons():
    routines = {"r1": _routine("A", 2022), "r2": _routine("A", 2023), "r3": _routine("B", 2023), "r4": _routine("C", 2024)}
    tracks = [_track("r1", "Boléro", "Maurice Ravel"), _track("r2", "Boléro", "Maurice Ravel"),
              _track("r3", "Bolero", "Dmitriy Khvorostovskiy"), _track("r4", "Other", "X")]
    rows = build_candidates(tracks, routines)
    bolero = rows[0]
    assert (bolero["work_key"], bolero["n_gymnasts"], bolero["n_routines"], bolero["n_tracks"]) == ("bolero", 2, 3, 3)
    assert (bolero["first_year"], bolero["last_year"], bolero["artist_check"]) == (2022, 2023, "different_authors")
    assert rows[1]["n_gymnasts"] == 1


def test_tracks_without_a_title_or_routine_are_ignored():
    routines = {"r1": _routine("A", 2022)}
    assert build_candidates([_track("r1", "", "X"), _track("missing", "Song", "Y")], routines) == []
