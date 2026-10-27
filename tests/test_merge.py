from rg_music.merge import expand_routines, merge_sources
from rg_music.years import expand_years


def routine(year, apparatus, music, row=0, notes=""):
    return {"gymnast_page": "A B", "table_index": "1", "row_index": str(row), "year": year, "apparatus": apparatus,
            "music": music, "notes": notes, "source_url": "u", "revid": "1"}


def comp(year, apparatus, music, competition="Athens 2004", location="Athens", row=0):
    return {"gymnast_page": "A B", "table_index": "0", "row_index": str(row), "year": year, "apparatus": apparatus,
            "music": music, "competition": competition, "location": location, "notes": "", "source_url": "u",
            "revid": "1"}


def test_expand_years():
    assert expand_years("2022/2023") == [2022, 2023]
    assert expand_years("2010-2012") == [2010, 2011, 2012]
    assert expand_years("2017-18") == [2017, 2018]
    assert expand_years("Year") == []


def test_season_becomes_one_row_per_year_that_differ_only_by_year():
    rows = expand_routines([routine("2022/2023", "Hoop", '"Forsaken" by Peter Crowley')])
    assert [(r["routine_id"], r["year"]) for r in rows] == [("A B|1|0#2022", 2022), ("A B|1|0#2023", 2023)]
    a, b = rows
    assert {k: v for k, v in a.items() if k not in ("routine_id", "year")} == \
           {k: v for k, v in b.items() if k not in ("routine_id", "year")}
    assert a["year_source"] == "2022/2023" and "expanded_from_season" in a["notes"]


def test_single_year_keeps_plain_id_and_no_season_note():
    (row,) = expand_routines([routine("2023", "Ball", "x")])
    assert (row["routine_id"], row["year"], row["year_source"], row["notes"]) == ("A B|1|0", 2023, "", "")


def test_same_performance_in_both_tables_is_merged_and_competition_becomes_an_event():
    merged, events, stats = merge_sources(
        [routine("2004", "Ball", "Syrtaki by D. Moutsis")], [comp("2004", "Ball", "Syrtaki by D. Moutsis")])
    assert len(merged) == 1 and merged[0]["source"] == "both"
    assert [(e["routine_id"], e["competition"]) for e in events] == [("A B|1|0", "Athens 2004")]
    assert stats["competition_rows_merged"] == 1


def test_one_routine_gets_several_events():
    _, events, _ = merge_sources(
        [routine("2004", "Ball", "Syrtaki by D. Moutsis")],
        [comp("2004", "Ball", "Syrtaki by D. Moutsis"),
         comp("2004", "Ball", "Syrtaki by D. Moutsis", competition="Worlds 2004", location="Budapest", row=1)])
    assert [e["competition"] for e in events] == ["Athens 2004", "Worlds 2004"]


def test_gymnast_with_only_a_competition_table_gets_new_routines():
    merged, events, stats = merge_sources([], [comp("2000", "Hoop", "Les Toreadors by Georges Bizet", "Sydney 2000", "Sydney")])
    assert [(m["year"], m["apparatus"], m["source"]) for m in merged] == [(2000, "Hoop", "competition_table")]
    assert merged[0]["routine_id"] == "A B|c0|0" and events[0]["competition"] == "Sydney 2000"
    assert stats["competition_rows_added"] == 1


def test_different_music_in_the_same_year_is_added_and_flagged_not_overwritten():
    merged, _, stats = merge_sources(
        [routine("2000", "Hoop", "Marche en la by Ennio Morricone")],
        [comp("2000", "Hoop", "Pink Dream by Anatoly Vekshin", "Sydney 2000", "Sydney")])
    assert len(merged) == 2
    assert "differs_from_routine_table" in next(m for m in merged if m["source"] == "competition_table")["notes"]
    assert stats["added_with_conflict"] == 1


def test_event_one_year_off_still_matches_and_keeps_the_routine_year():
    merged, events, _ = merge_sources(
        [routine("2020", "Ball", "Strange Birds by Birdy")],
        [comp("2021", "Ball", "Strange Birds by Birdy", "Tokyo 2020", "Tokyo")])
    assert len(merged) == 1 and merged[0]["year"] == 2020 and "event_year_differs" in merged[0]["notes"]
    assert events[0]["event_year"] == 2021


def test_rows_without_music_or_single_apparatus_are_skipped():
    merged, events, stats = merge_sources([], [comp("2004", "Ball", ""), comp("2004", "All-around", "x by y")])
    assert merged == [] and events == [] and stats["competition_rows_skipped"] == 2


def test_same_title_with_different_wrapping_is_the_same_music():
    merged, _, stats = merge_sources([routine("2008", "Hoop", "music from Avrora by Valeri Tishler")],
                                     [comp("2008", "Hoop", "Avrora by Valeri Tishler")])
    assert len(merged) == 1 and stats["competition_rows_merged"] == 1


def test_one_track_of_a_multi_track_cell_matches():
    merged, _, _ = merge_sources([routine("2012", "Clubs", "Beat Machine / The Expert / Tradition by Gloria Estefan")],
                                 [comp("2012", "Clubs", "Beat Machine by Gloria Estefan")])
    assert len(merged) == 1


def test_expanded_season_drops_the_stale_year_note():
    rows = expand_routines([routine("2022/2023", "Hoop", "x", notes="year_not_a_year")])
    assert all("year_not_a_year" not in r["notes"] for r in rows)


def test_owner_can_merge_rows_whose_wording_differs():
    r, c = routine("2008", "Rope", "Gopak (Ukrainian traditional)"), comp("2008", "Rope", "Hopak – Ukrainian Folk")
    merged, _, _ = merge_sources([r], [c])
    assert len(merged) == 2 and "differs_from_routine_table" in merged[1]["notes"]
    same = {("A B", 2008, "Rope", "Hopak – Ukrainian Folk", "Gopak (Ukrainian traditional)")}
    merged, events, _ = merge_sources([r], [c], same)
    assert len(merged) == 1 and merged[0]["source"] == "both" and "same_routine_by_owner" in merged[0]["notes"]
    assert events[0]["routine_id"] == merged[0]["routine_id"]


def test_owner_can_exclude_a_routine_the_source_states_wrongly():
    rows = [routine("2020", "Hoop (first)", '"Largo Al Factotum", by Denis Matsuev', row=1), routine("2020", "Ball", "x", row=2)]
    merged, _, stats = merge_sources(rows, [], exclusions={("A B", "2020", "Hoop (first)", '"Largo Al Factotum", by Denis Matsuev')})
    assert [m["routine_id"] for m in merged] == ["A B|1|2"] and stats["excluded_by_owner"] == ["A B|1|1"]


def test_owner_rows_that_match_nothing_are_reported():
    r, c = routine("2008", "Rope", "Gopak"), comp("2008", "Rope", "Hopak")
    same = {("A B", 2008, "Rope", "Hopak", "Gopak"), ("A B", 2009, "Ball", "old text", "older text")}
    stale = ("A B", "2020", "Hoop", "text before the article was edited")
    _, _, stats = merge_sources([r], [c], same, exclusions={stale})
    assert stats["unused_owner_rows"] == ["routine_exclusions: A B | 2020 | Hoop | text before the article was edited",
                                          "same_routine: A B | 2009 | Ball | old text | older text"]


def test_owner_rows_fill_gaps_repeat_noted_years_and_flag_conflicts():
    from rg_music.merge import merge_owner
    merged = [{"gymnast_page": "G", "year": 2012, "apparatus": "Ribbon", "music": "Move by Said Mrad"},
              {"gymnast_page": "G", "year": 2011, "apparatus": "Ball", "music": "Yesterday by the Beatles"}]
    owner = [{"sheet_row": "2", "gymnast_page": "G", "year": "2011", "apparatus": "Ribbon", "music": "19 Palqu by X",
              "note": "Same as in 2012"},
             {"sheet_row": "3", "gymnast_page": "G", "year": "2011", "apparatus": "Ball", "music": "Yesterday by The Beatles",
              "note": ""},
             {"sheet_row": "4", "gymnast_page": "G", "year": "2011", "apparatus": "Hoop", "music": "", "note": ""}]
    added, stats = merge_owner(merged, owner)
    assert [(a["year"], a["apparatus"], a["notes"]) for a in added] == [
        (2011, "Ribbon", "found_by_owner"),
        (2012, "Ribbon", "found_by_owner;repeated_from_owner_note;differs_from_wikipedia")]
    assert stats == {"owner_rows_added": 1, "owner_rows_added_with_conflict": 1, "owner_rows_same_as_wikipedia": 1,
                     "owner_rows_without_music": 1}
