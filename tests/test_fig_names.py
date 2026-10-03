from rg_music.fig_names import carry_over, fig_ids, normalize_fig_name


def test_fig_name_is_turned_into_given_then_surname():
    assert normalize_fig_name("AVERINA Dina") == "Dina Averina"
    assert normalize_fig_name("VALDEZ PEREZ Cynthia Yasmin") == "Cynthia Yasmin Valdez Perez"
    assert normalize_fig_name("BOGDANOVA-SELEDTSOVA Viktoria") == "Viktoria Bogdanova-Seledtsova"
    assert normalize_fig_name("Dina") == "Dina"  # nothing to recognise: left as is


def test_fig_ids_from_wikidata_claims():
    entity = {"claims": {
        "P2696": [{"mainsnak": {"datavalue": {"value": "18528"}}}],
        "P7440": [{"mainsnak": {"datavalue": {"value": "34455"}}}],
    }}
    assert fig_ids(entity) == ("18528", "34455")
    assert fig_ids({}) == ("", "")
    assert fig_ids({"claims": {"P2696": [{"mainsnak": {"snaktype": "novalue"}}]}}) == ("", "")


def test_rebuilding_the_sheet_keeps_earlier_decisions():
    rows = [{"gymnast_key": "k1", "reason": "possible_duplicate", "decision": "", "canonical_name": ""},
            {"gymnast_key": "k2", "reason": "spelling_variants", "decision": "", "canonical_name": ""}]
    previous = [{"gymnast_key": "k1", "reason": "possible_duplicate", "decision": "same",
                 "canonical_name": "Eileen Word", "decision_basis": ""}]
    out = carry_over(rows, previous)
    assert (out[0]["decision"], out[0]["canonical_name"], out[0]["decision_basis"]) == ("same", "Eileen Word", "")
    assert out[1]["decision"] == "" and out[1]["decision_basis"] == ""
