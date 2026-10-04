from rg_music.apparatus import NAMES_RU
from rg_music.countries import build_reference
from rg_music.names_ru import clean_ru_name, russian_name


def test_surname_first_with_patronymic_becomes_given_surname():
    assert clean_ru_name("Солдатова, Александра Сергеевна") == ("Александра Солдатова", False)


def test_plain_and_hyphenated_names_are_kept():
    assert clean_ru_name("Агнешка Брандебура") == ("Агнешка Брандебура", False)
    assert clean_ru_name("Александра Кирой-Богатырёва") == ("Александра Кирой-Богатырёва", False)


def test_trailing_bracket_is_dropped():
    assert clean_ru_name("Руссо, Алессия (гимнастка)") == ("Алессия Руссо", False)


def test_three_words_left_goes_to_review():
    assert clean_ru_name("Адриана Владимирова Дунавская")[1] is True


def test_only_cyrillic_names_are_accepted_label_first():
    assert russian_name("Александра Солдатова", "Солдатова, Александра") == ("Александра Солдатова", "wikidata_label")
    assert russian_name("Aleksandra Soldatova", "Солдатова, Александра") == ("Солдатова, Александра", "ruwiki_title")
    assert russian_name("Aleksandra Soldatova", "") == ("", "")


def test_apparatus_have_russian_names():
    assert NAMES_RU["Ribbon"] == "Лента" and NAMES_RU["Clubs"] == "Булавы" and len(NAMES_RU) == 7


def test_countries_have_short_russian_names():
    ru = {c["country_id"]: c["name_ru"] for c in build_reference()[0]}
    assert (ru["RUS"], ru["KOR"], ru["SUHH"], ru["CSHH"], ru["USA"]) == ("Россия", "Южная Корея", "СССР", "Чехословакия", "США")
    assert ru["DEU"] == "Германия"


def test_surname_ending_like_a_patronymic_is_not_dropped():
    assert clean_ru_name("Александра Наркевич") == ("Александра Наркевич", False)
    assert clean_ru_name("Алина Маратовна Кабаева") == ("Алина Кабаева", False)
    assert clean_ru_name("Гусейнова, Вафа Феяз кызы") == ("Вафа Феяз Гусейнова", True)
