import pytest

from rg_music.countries import CountryReference, build_reference, normalize


@pytest.fixture(scope="module")
def ref():
    return CountryReference(*build_reference())


def test_reference_has_current_and_former_countries():
    countries, _ = build_reference()
    ids = {c["country_id"]: c for c in countries}
    assert ids["RUS"]["name"] == "Russia" and ids["RUS"]["status"] == "current"
    assert ids["KOR"]["name"] == "South Korea"
    assert ids["CZE"]["name"] == "Czech Republic"
    assert ids["SUHH"]["status"] == "former" and ids["SUHH"]["valid_until"].startswith("1992")
    assert ids["CSHH"]["name"] == "Czechoslovakia" and ids["DDDE"]["name"] == "East Germany"
    assert ids["AIN"]["status"] == "other"


def test_normalize_drops_years_brackets_article_and_accents():
    assert normalize("Venezuela (1930–2006)") == "venezuela"
    assert normalize("the Soviet Union") == "soviet union"
    assert normalize("Côte d'Ivoire") == "cote d ivoire"


@pytest.mark.parametrize("text, country_id, method", [
    ("Czech Republic", "CZE", "exact"),
    ("the Czech Republic", "CZE", "exact"),
    ("Venezuela (1930–2006)", "VEN", "exact"),
    ("the People's Republic of China", "CHN", "exact"),
    ("Georgia (country)", "GEO", "exact"),
    ("West Germany", "DEU", "exact"),
    ("East Germany", "DDDE", "exact"),
    ("Soviet Union", "SUHH", "exact"),
    ("Korea", "KOR", "exact"),
    ("Taiwan", "TWN", "exact"),
    ("KAZ", "KAZ", "code"),
    ("GER", "DEU", "code"),
    ("SLO", "SVN", "code"),
    ("Chinese Taipei for Olympic Games", "TWN", "contained"),
    ("Czech Republik", "CZE", "fuzzy"),
])
def test_match(ref, text, country_id, method):
    m = ref.match(text)
    assert (m.country_id, m.method) == (country_id, method)


def test_unknown_country_is_not_guessed(ref):
    m = ref.match("Atlantis")
    assert (m.country_id, m.method, m.needs_review) == ("", "none", True)
    assert not ref.match("Hungary").needs_review
    assert ref.match("Hungry").needs_review  # fuzzy matches are always for review


def test_fuzzy_does_not_confuse_neighbours(ref):
    assert ref.match("Niger").country_id == "NER"
    assert ref.match("Nigeria").country_id == "NGA"
    assert ref.match("Guinea").country_id == "GIN"
