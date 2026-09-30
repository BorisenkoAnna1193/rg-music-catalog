from rg_music.events import normalize_event


def test_tokyo_dated_2020_is_corrected_to_2021():
    assert normalize_event("Olympics", "Tokyo", "2020") == (
        "Tokyo 2020", "2021", ["year_corrected_2020_to_2021"]
    )


def test_tokyo_already_2021_is_left_alone():
    assert normalize_event("Olympics", "Tokyo", "2021") == ("Tokyo 2020", "2021", [])


def test_other_games_get_official_name():
    assert normalize_event("Olympics", "Rio de Janeiro", "2016") == ("Rio 2016", "2016", [])


def test_non_olympic_competition_untouched():
    assert normalize_event("World Championships", "Baku", "2019") == (
        "World Championships", "2019", []
    )
