from rg_music.name_decisions import Clusters, best_name, build_final, decide, latest_country, pair_decision


def row(**kw):
    base = {"reason": "spelling_variants", "group": "1", "display_name": "", "wiki_page": "", "nations": "",
            "years": "", "spellings": "", "gymnast_key": "k", "decision": "", "canonical_name": "",
            "fig_id": "", "fig_name": "", "decision_basis": ""}
    return {**base, **kw}


def test_fig_name_wins_and_surname_is_capitalised():
    r = row(fig_name="AVERINA Dina", wiki_page="Dina Averina (gymnast)", spellings="Dina Averina (2019)")
    assert best_name([r]) == ("Dina Averina", "fig")


def test_wikipedia_title_when_no_fig_and_disambiguation_is_dropped():
    r = row(wiki_page="Li Hongyang (gymnast)", spellings="Hongyang Li (2009)")
    assert best_name([r]) == ("Li Hongyang", "wikipedia")


def test_table_spelling_most_frequent_then_latest():
    r = row(spellings="Seo Goeun (2021) | Goeun Seo (2018)")
    assert best_name([r]) == ("Seo Goeun", "table")
    r = row(spellings="A Name (2001,2005) | B Name (2009)")
    assert best_name([r]) == ("A Name", "table")


def test_pair_same_when_fig_names_equal():
    a, b = row(fig_name="JOVANOVIC Anja", display_name="Anja Jovanovic"), row(fig_name="JOVANOVIC Anja", display_name="Anja Jovanović")
    assert pair_decision(a, b, False)[0] == "same"


def test_pair_different_when_fig_names_differ_or_same_table():
    a, b = row(fig_name="GARCIA Natalia"), row(fig_name="GARCIA Natalie")
    assert pair_decision(a, b, False)[0] == "different"
    assert pair_decision(row(display_name="A B"), row(display_name="A B"), True)[0] == "different"


def test_pair_same_for_identical_name_in_two_countries_even_with_word_order_swap():
    a = row(display_name="Joowon Kim", nations="Korea")
    b = row(display_name="Kim Joowon", nations="South Korea")
    assert pair_decision(a, b, False)[0] == "same"


def test_pair_same_country_is_assumed_same_otherwise_different():
    a, b = row(display_name="Eileen Ward", nations="United Kingdom"), row(display_name="Eileen Word", nations="United Kingdom")
    assert pair_decision(a, b, False) == ("same", "same country, never in the same table (assumed)")
    c, d = row(display_name="Viktoria Bogdanova", nations="Estonia"), row(display_name="Viktoria Danova", nations="Bulgaria")
    assert pair_decision(c, d, False)[0] == "different"


def test_latest_country_is_the_country_of_the_last_championship():
    apps = [{"year": "1969", "nation": "France"}, {"year": "1973", "nation": "West Germany"},
            {"year": "1975", "nation": "France"}]
    assert latest_country(apps)[1] == "France"
    assert latest_country(apps[:2])[1] == "West Germany"


def test_latest_country_prefers_reference_names_and_merges_labels_of_one_country():
    apps = [{"year": "1971", "nation": "Czech Republic", "country_id": "CZE", "country": "Czech Republic"},
            {"year": "1973", "nation": "Czechoslovakia", "country_id": "CSHH", "country": "Czechoslovakia"},
            {"year": "1975", "nation": "the Czech Republic", "country_id": "CZE", "country": "Czech Republic"}]
    cid, name, history = latest_country(apps)
    assert (cid, name) == ("CZE", "Czech Republic")
    assert history == "Czech Republic 1971-1975 > Czechoslovakia 1973"


def test_owner_decision_is_not_overwritten_and_pair_is_merged():
    a = row(reason="possible_duplicate", gymnast_key="page:1", display_name="X Y", spellings="X Y (2001)",
            nations="Italy", decision="different")  # typed by the owner: no decision_basis
    b = row(reason="possible_duplicate", gymnast_key="name:b", display_name="X Y", spellings="X Y (2003)", nations="Italy")
    apps = [{"gymnast_key": "page:1", "year": "2001", "stage": "all-around", "nation": "Italy", "name": "X Y"},
            {"gymnast_key": "name:b", "year": "2003", "stage": "all-around", "nation": "Italy", "name": "X Y"}]
    decide([a, b], apps)
    assert a["decision"] == "different" and b["decision"] == "different"
    gymnasts = [{"gymnast_key": "page:1", "display_name": "X Y", "wiki_page": ""},
                {"gymnast_key": "name:b", "display_name": "X Y", "wiki_page": ""}]
    assert len(build_final(gymnasts, [a, b], apps)) == 2


def test_same_pair_becomes_one_person_with_latest_country():
    a = row(reason="possible_duplicate", gymnast_key="k1", display_name="Ute Barylla", spellings="Ute Barylla (1971)", nations="Germany")
    b = row(reason="possible_duplicate", gymnast_key="k2", display_name="Ute Barylla", spellings="Ute Barylla (1975)", nations="West Germany")
    apps = [{"gymnast_key": "k1", "year": "1971", "stage": "all-around", "nation": "Germany", "name": "Ute Barylla"},
            {"gymnast_key": "k2", "year": "1975", "stage": "all-around", "nation": "West Germany", "name": "Ute Barylla"}]
    decide([a, b], apps)
    gymnasts = [{"gymnast_key": k, "display_name": "Ute Barylla", "wiki_page": ""} for k in ("k1", "k2")]
    final = build_final(gymnasts, [a, b], apps)
    assert len(final) == 1 and final[0]["country"] == "West Germany" and final[0]["years"] == "1971,1975"


def test_clusters_are_transitive():
    c = Clusters()
    c.union("a", "b"); c.union("b", "c")
    assert c.find("a") == c.find("c")


def test_neutral_athletes_status_is_not_chosen_as_latest_country():
    apps = [{"year": "2021", "nation": "Belarus", "country_id": "BLR", "country": "Belarus"},
            {"year": "2026", "nation": "Individual Neutral Athletes", "country_id": "AIN",
             "country": "Individual Neutral Athletes"}]
    cid, name, history = latest_country(apps, frozenset({"AIN"}))
    assert (cid, name) == ("BLR", "Belarus") and "Individual Neutral Athletes 2026" in history
    assert latest_country(apps[1:], frozenset({"AIN"}))[0] == "AIN"  # nothing else to choose
