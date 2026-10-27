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
    rows = [{"group": "7", "gymnast_key": "k1", "reason": "possible_duplicate", "decision": "", "canonical_name": ""},
            {"group": "7", "gymnast_key": "k3", "reason": "possible_duplicate", "decision": "", "canonical_name": ""},
            {"group": "8", "gymnast_key": "k2", "reason": "spelling_variants", "decision": "", "canonical_name": ""}]
    previous = [{"group": "3", "gymnast_key": "k1", "reason": "possible_duplicate", "decision": "same",
                 "canonical_name": "Eileen Word", "decision_basis": ""},
                {"group": "3", "gymnast_key": "k3", "reason": "possible_duplicate", "decision": "same",
                 "canonical_name": "Eileen Word", "decision_basis": ""}]
    out = carry_over(rows, previous)  # group numbers change between builds; the pair is what counts
    assert (out[0]["decision"], out[0]["canonical_name"], out[0]["decision_basis"]) == ("same", "Eileen Word", "")
    assert out[1]["decision"] == "same"
    assert out[2]["decision"] == "" and out[2]["decision_basis"] == ""


def test_a_new_look_alike_does_not_inherit_the_old_pair_decision():
    previous = [{"group": "1", "gymnast_key": "k1", "reason": "possible_duplicate", "decision": "different",
                 "canonical_name": "", "decision_basis": ""},
                {"group": "1", "gymnast_key": "k2", "reason": "possible_duplicate", "decision": "different",
                 "canonical_name": "", "decision_basis": ""}]
    rows = [{"group": "1", "gymnast_key": "k1", "reason": "possible_duplicate", "decision": "", "canonical_name": ""},
            {"group": "1", "gymnast_key": "k2", "reason": "possible_duplicate", "decision": "", "canonical_name": ""},
            {"group": "2", "gymnast_key": "k1", "reason": "possible_duplicate", "decision": "", "canonical_name": ""},
            {"group": "2", "gymnast_key": "new", "reason": "possible_duplicate", "decision": "", "canonical_name": ""}]
    out = carry_over(rows, previous)
    assert [r["decision"] for r in out] == ["different", "different", "", ""]
