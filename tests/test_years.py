import pytest

from rg_music.years import parse_years


@pytest.mark.parametrize("text, expected", [
    ("2023", (2023, 2023)),
    ("2022/2023", (2022, 2023)),
    ("2020-2021", (2020, 2021)),
    ("2017-18", (2017, 2018)),
    ("1999-00", (1999, 2000)),
    ("2020/2021/2022", (2020, 2022)),
    ("2010-2012", (2010, 2012)),
    ("2015–2016", (2015, 2016)),
])
def test_parse_years(text, expected):
    assert parse_years(text) == expected


@pytest.mark.parametrize("text", ["Year", "", "n/a", "23", "2023 World Championships"])
def test_not_a_year(text):
    assert parse_years(text) is None
