from rg_music.wiki_client import _cache_key


def test_ascii_titles_keep_their_key_and_other_scripts_never_collide():
    assert _cache_key("Almudena Cid") == "Almudena_Cid"
    a, b = _cache_key("Кабаева, Алина Маратовна"), _cache_key("Тимошенко, Александра Владимировна")
    assert a != b and a and b
    assert _cache_key("Кабаева, Алина Маратовна") == a  # stable between runs
