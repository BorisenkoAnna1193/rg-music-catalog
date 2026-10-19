from rg_music.work_review import build_review


def tw(rid, title, key, split_key=None, cluster="caruso"):
    return {"routine_id": rid, "track_no": "1", "title": title, "work_key": key, "split_key": split_key or key,
            "title_cluster": cluster}


def test_open_titles_get_lettered_groups_with_the_evidence_and_a_prefilled_decision():
    routines = {k: {"gymnast_page": g, "year": y, "apparatus": "Ball"} for k, g, y in
                [("a", "A1", "2010"), ("b", "B1", "2012"), ("c", "C1", "2018"), ("d", "D1", "2020"), ("e", "E1", "2015")]}
    rows = [tw("a", "Caruso", "caruso", "caruso ~ lara fabian"), tw("b", "Caruso", "caruso", "caruso ~ luciano pavarotti"),
            tw("c", "Caruso", "caruso ~ filippa giordano"), tw("d", "Caruso", "caruso ~ no credit"),
            tw("e", "Hello", "hello", cluster="hello")]  # one work only: nothing to review
    links = {"caruso ~ lara fabian": {"mb_work_id": "w1", "mb_work_title": "Caruso", "mb_writers": "Lucio Dalla"}}
    out = build_review(rows, routines, {("a", "1"): "Caruso by Lara Fabian"}, links)
    assert [(r["gymnast"], r["group"], r["decision"], r["evidence"]) for r in out] == [
        ("A1", "A", "A", "MusicBrainz: Lucio Dalla"), ("B1", "A", "A", "MusicBrainz: Lucio Dalla"),
        ("C1", "B", "B", "none"), ("D1", "C", "C", "no credit")]
    assert out[0]["source_text"] == "Caruso by Lara Fabian" and out[0]["title_gymnasts"] == 4
    assert [r["row_id"] for r in out] == [1, 2, 3, 4]


def test_owner_sheet_becomes_decisions_per_split_group():
    from rg_music.work_review import import_decisions
    review = [{"row_id": "1", "title_no": "1", "group": "A", "routine_id": "a", "track_no": "1"},
              {"row_id": "2", "title_no": "1", "group": "B", "routine_id": "b", "track_no": "1"},
              {"row_id": "3", "title_no": "1", "group": "C", "routine_id": "c", "track_no": "1"}]
    tws = [{"routine_id": k, "track_no": "1", "title_cluster": "caruso", "split_key": f"caruso ~ {k}"} for k in "abc"]
    sheet = [{"row_id": "1", "decision": "A", "owner_note": ""}, {"row_id": "2", "decision": "a", "owner_note": "same song"},
             {"row_id": "3", "decision": "C", "owner_note": "a different song"}]
    got = import_decisions(sheet, review, tws, "test")
    assert [(r["split_key"], r["join_to"], r["owner_note"]) for r in got] == [
        ("caruso ~ b", "caruso ~ a", "same song"), ("caruso ~ c", "", "a different song")]


def test_a_sheet_that_does_not_match_the_local_rows_is_refused():
    import pytest
    from rg_music.work_review import import_decisions
    review = [{"row_id": "1", "title_no": "1", "group": "A", "routine_id": "a", "track_no": "1", "source_text": "Caruso by X"}]
    tws = [{"routine_id": "a", "track_no": "1", "title_cluster": "caruso", "split_key": "caruso ~ x"}]
    with pytest.raises(ValueError):
        import_decisions([{"row_id": "1", "decision": "A", "owner_note": "", "source_text": "Hello by Y"}], review, tws, "t")


def test_second_round_keeps_earlier_decisions_and_has_only_new_titles():
    from rg_music.work_review import merge_decisions, only_new_titles
    old = [{"title_cluster": "caruso", "split_key": "caruso ~ b", "join_to": "caruso ~ a", "owner_note": "", "source": "1"}]
    new = [{"title_cluster": "hero", "split_key": "hero ~ b", "join_to": "", "owner_note": "other song", "source": "2"}]
    assert [r["split_key"] for r in merge_decisions(old, new)] == ["caruso ~ b", "hero ~ b"]
    rows = [{"row_id": 1, "title_no": 1, "work_key": "caruso ~ a"}, {"row_id": 2, "title_no": 2, "work_key": "hero ~ b"}]
    assert only_new_titles(rows, [{"work_key": "caruso ~ a"}]) == [{"row_id": 1, "title_no": 1, "work_key": "hero ~ b"}]
