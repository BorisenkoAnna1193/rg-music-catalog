import pytest

from rg_music.apparatus import normalize_apparatus


@pytest.mark.parametrize("raw, expected", [
    ("Hoop", ("Hoop", "", "")),
    ("Ribbons", ("Ribbon", "", "")),
    ("Hoop (2nd)", ("Hoop", "second", "")),
    ("Clubs (Second)", ("Clubs", "second", "")),
    ("Ball (third)", ("Ball", "third", "")),
    ("Gala at EC Minsk", ("Gala", "", "EC Minsk")),
    ("Clubs (Aeon Cup)", ("Clubs", "", "Aeon Cup")),
    ("Clubs at LA Lights", ("Clubs", "", "LA Lights")),
    ("Gala-free hand", ("Gala", "", "free hand")),
    ("Gala-2 Ribbons (WCH Patras)", ("Gala", "", "2 Ribbons; WCH Patras")),
    ("Free-hands", ("Free hands", "", "")),
])
def test_normalize(raw, expected):
    assert normalize_apparatus(raw)[:3] == expected


def test_typo_is_fixed_and_flagged():
    a = normalize_apparatus("Gala-Autum")
    assert a.context == "Autumn"
    assert a.notes == ["typo_fixed_Autum_to_Autumn"]


def test_unknown_apparatus_is_flagged():
    assert normalize_apparatus("Dance").notes == ["unknown_apparatus"]
