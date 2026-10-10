from rg_music.works import find_alias, fuzzy_groups, load_aliases, resolve_works


def info(**kw):
    return {k: {"gymnasts": g, "tracks": g, "artists": a} for k, (g, a) in kw.items()}


def test_long_spelling_variants_are_merged_into_the_most_used_spelling():
    rep, review = fuzzy_groups(info(**{"california dreamin": (2, ["Mamas"]), "carlifornia dreamin": (1, [])}))
    assert rep["carlifornia dreamin"] == rep["california dreamin"] == "california dreamin" and review == []


def test_different_performers_do_not_block_a_merge():
    rep, _ = fuzzy_groups(info(**{"polovtsian dances": (1, ["Borodin"]), "polovetsian dances": (1, ["Kirov Orchestra"])}))
    assert rep["polovetsian dances"] == rep["polovtsian dances"]


def test_short_generic_titles_and_plurals_go_to_review_not_merged():
    rep, review = fuzzy_groups(info(**{"main title": (5, ["X"]), "main titles": (1, ["Y"])}))
    assert rep["main title"] != rep["main titles"]
    assert review[0]["why_not_merged"] == "short or generic title"


def test_numbers_must_match():
    rep, review = fuzzy_groups(info(**{"piano concerto no 2 in c minor": (1, []), "piano concerto no 3 in c minor": (1, [])}))
    assert rep["piano concerto no 2 in c minor"] != rep["piano concerto no 3 in c minor"]
    assert review[0]["why_not_merged"] == "different numbers"


ROUTINES = {f"r{i}": {"gymnast_page": g, "year": str(y)} for i, (g, y) in enumerate(
    [("Petrova", 1993), ("Rodriguez", 2001), ("Bessonova", 2009), ("Nikolchenko", 2018), ("Nikolchenko", 2020), ("Ruprecht", 2017)])}


def track(rid, title, artist):
    return {"routine_id": rid, "track_no": "1", "title": title, "artist": artist}


def aliases(tmp_path):
    path = tmp_path / "a.csv"
    path.write_text(
        "title_key,artist_contains,work,excerpt,composer,note\n"
        "o fortuna,Orff,Carmina Burana,O Fortuna,Carl Orff,\n"
        "carmina burana o fortuna,,Carmina Burana,O Fortuna,Carl Orff,\n"
        "carmina burana,Synthesizer,Carmina Burana,O Fortuna,Carl Orff,\n"
        "carmina burana,,Carmina Burana,,Carl Orff,\n", encoding="utf-8")
    return load_aliases(path)


def test_carmina_burana_in_every_spelling_is_one_work_with_the_o_fortuna_excerpt(tmp_path):
    tracks = [track("r0", "Carmina Burana", "Synthesizer"), track("r1", "Fortuna Imperatrix Mundi: O Fortuna", "Carl Orff"),
              track("r2", "Carmina Burana", "Carl Orff"), track("r3", "Carmina Burana: O Fortuna", "Carl Orff"),
              track("r4", "O Fortuna", "Carl Orff"), track("r5", "Carmina Burana", "André Rieu")]
    al = aliases(tmp_path)
    al.append({"title_key": "fortuna imperatrix mundi o fortuna", "artist_contains": "", "work": "Carmina Burana",
               "excerpt": "O Fortuna", "composer": "Carl Orff", "note": ""})
    rows, works, _ = resolve_works(tracks, ROUTINES, al)
    assert {r["work_key"] for r in rows} == {"carmina burana"}
    by_gymnast = {ROUTINES[r["routine_id"]]["gymnast_page"]: r["excerpt"] for r in rows}
    assert by_gymnast["Petrova"] == "O Fortuna" and by_gymnast["Bessonova"] == "" and by_gymnast["Nikolchenko"] == "O Fortuna"
    assert works[0]["n_gymnasts"] == 5 and works[0]["composer"] == "Carl Orff" and works[0]["work"] == "Carmina Burana"


def test_alias_with_an_artist_filter_wins_over_the_general_one(tmp_path):
    al = aliases(tmp_path)
    assert find_alias("carmina burana", "Synthesizer", al)["excerpt"] == "O Fortuna"
    assert find_alias("carmina burana", "Carl Orff", al)["excerpt"] == ""
    assert find_alias("o fortuna", "Someone Else", al) is None


def test_work_colon_excerpt_needs_a_track_with_the_work_title_and_a_shared_credit():
    routines = {"a": {"gymnast_page": "A", "year": "2020"}, "b": {"gymnast_page": "B", "year": "2021"},
                "c": {"gymnast_page": "C", "year": "2022"}, "d": {"gymnast_page": "D", "year": "2022"}}
    tracks = [track("a", "Carmen", "Georges Bizet"), track("b", "Carmen: Habanera", "Georges Bizet"),
              track("c", "Opening", "Marvin Hamlisch"), track("d", "Opening: I Hope I Get It", "Original Cast")]
    rows, works, _ = resolve_works(tracks, routines, [])
    by = {r["title"]: r for r in rows}
    assert (by["Carmen: Habanera"]["work_key"], by["Carmen: Habanera"]["excerpt"], by["Carmen: Habanera"]["method"]) == (
        "carmen", "Habanera", "colon_prefix")
    assert by["Opening: I Hope I Get It"]["method"] == "title"  # credits differ: not the same "Opening"
    assert next(w for w in works if w["work_key"] == "carmen")["n_gymnasts"] == 2


def test_a_composer_before_the_colon_is_not_taken_for_the_work():
    routines = {"a": {"gymnast_page": "A", "year": "2020"}, "b": {"gymnast_page": "B", "year": "2021"}}
    tracks = [track("a", "Nocturne", "Chopin"), track("b", "Chopin: Fantasie", "Chopin")]
    rows, _, _ = resolve_works(tracks, routines, [])
    row = next(r for r in rows if r["title"] == "Chopin: Fantasie")
    assert (row["method"], row["composer"], row["work"]) == ("composer_prefix", "Chopin", "Fantasie")


def test_from_work_links_an_excerpt_only_when_the_work_is_a_track_of_its_own():
    routines = {k: {"gymnast_page": k.upper(), "year": "2020"} for k in "abcd"}
    tracks = [track("a", "Spartacus", "Aram Khachaturian"),
              {**track("b", "At the Circus", "Aram Khatchaturian"), "work": "Spartacus"},
              track("c", "Money, Money, Money", "ABBA"),
              {**track("d", "Money, Money, Money", "Meryl Streep"), "work": "Mamma Mia!"}]
    rows, works, _ = resolve_works(tracks, routines, [])
    by = {r["routine_id"]: r for r in rows}
    assert (by["b"]["work_key"], by["b"]["excerpt"], by["b"]["method"]) == ("spartacus", "At the Circus", "from_work")
    assert by["d"]["method"] == "title"  # "Mamma Mia!" is only the source
    # ABBA and Meryl Streep share no name: kept apart until there is evidence (MusicBrainz) that it is one song
    assert (by["c"]["work_key"], by["d"]["work_key"]) == ("money money money ~ abba", "money money money ~ meryl streep")
    assert next(w for w in works if w["work_key"] == "spartacus")["n_gymnasts"] == 2


def test_same_title_different_authors_can_be_different_works_and_the_credit_decides(tmp_path):
    path = tmp_path / "a.csv"
    path.write_text(
        "title_key,artist_contains,work,excerpt,composer,note,work_key\n"
        "carmen suite,Shchedrin,Carmen Suite,,Rodion Shchedrin,,\n"          # Shchedrin before Bizet: his credit names both
        "carmen suite,Bizet,Carmen,Carmen Suite,Georges Bizet,,\n"
        "carmen,Stromae,Carmen (Stromae),,Stromae,,carmen stromae\n", encoding="utf-8")
    routines = {k: {"gymnast_page": k.upper(), "year": "2020"} for k in "abcde"}
    tracks = [track("a", "Carmen", "Georges Bizet"), track("b", "Carmen", "Stromae"),
              track("c", "Carmen Suite", "Rodion Shchedrin / Bizet"), track("d", "Carmen Suite", "Georges Bizet, Moscow Virtuosi"),
              track("e", "Carmen", "Arcadian")]
    rows, works, _ = resolve_works(tracks, routines, load_aliases(path))
    key = {r["routine_id"]: r["work_key"] for r in rows}
    assert key["a"] == key["d"] == key["e"] == "carmen"          # Bizet's opera (d: Bizet's own suite) and the unverified one
    assert key["b"] == "carmen stromae" and key["c"] == "carmen suite"
    assert next(w for w in works if w["work_key"] == "carmen stromae")["work"] == "Carmen (Stromae)"


def test_one_title_with_unrelated_credits_is_split_into_works_and_a_lone_uncredited_track_gets_its_own():
    routines = {k: {"gymnast_page": k.upper(), "year": "2020"} for k in "abcde"}
    tracks = [track("a", "Storm", "Otyken"), track("b", "The Storm", "Balázs Havasi"), track("c", "The storm", "Havasi"),
              track("d", "Storm", ""), track("e", "Caravan", "Duke Ellington")]
    rows, works, _ = resolve_works(tracks, routines, [])
    key = {r["routine_id"]: r["work_key"] for r in rows}
    assert key["a"] == "storm ~ otyken" and key["b"] == key["c"] == "storm ~ balazs havasi"
    assert key["d"] == "storm ~ no credit" and key["e"] == "caravan"
    assert next(w for w in works if w["work_key"] == "storm ~ balazs havasi")["n_gymnasts"] == 2


def test_one_classical_composer_keeps_a_specific_title_together_but_not_a_generic_one():
    routines = {k: {"gymnast_page": k.upper(), "year": "2020"} for k in "abcdef"}
    tracks = [track("a", "Für Elise", "Beethoven"), track("b", "Fur Elise", "Hidden Citizens"),
              track("c", "Requiem", "Mozart"), track("d", "Requiem", "Alma"),
              track("e", "Bolero", "Maurice Ravel"), track("f", "Boléro", "London Symphony Orchestra, Maurice Ravel")]
    rows, works, _ = resolve_works(tracks, routines, [])
    by = {r["routine_id"]: r for r in rows}
    assert by["a"]["work_key"] == by["b"]["work_key"] == "fur elise" and by["b"]["same_title"] == "kept_classical_title"
    assert by["c"]["work_key"] != by["d"]["work_key"]
    # versions: the composer is not a performer; "by Maurice Ravel" alone is an unknown recording
    assert (by["a"]["performer"], by["b"]["performer"]) == ("", "Hidden Citizens")
    assert by["e"]["version_key"] == "bolero | unknown" and by["f"]["performer"] == "London Symphony Orchestra"
    assert next(w for w in works if w["work_key"] == "fur elise")["n_versions"] == 2


def test_spellings_of_one_performer_are_one_version():
    routines = {k: {"gymnast_page": k.upper(), "year": "2020"} for k in "abcde"}
    tracks = [track("a", "Run the World (Girls)", "Beyoncé"), track("b", "Run the World", "Beyonce"),
              track("c", "Run the World", "The Beyonce"), track("d", "California Dreamin'", "33Tours"),
              track("e", "California Dreamin'", "33 Tours")]
    rows, works, _ = resolve_works(tracks, routines, [])
    assert len({r["version_key"] for r in rows}) == 2 and all(w["n_versions"] == 1 for w in works)
    assert {r["work_key"] for r in rows} == {"run the world", "california dreamin"}


def test_groups_that_musicbrainz_shows_to_be_one_song_are_joined_again():
    routines = {k: {"gymnast_page": k.upper(), "year": "2020"} for k in "abcd"}
    tracks = [track("a", "Smooth Criminal", "Michael Jackson"), track("b", "Smooth Criminal", "David Garrett"),
              track("c", "Smooth Criminal", "2 Cellos"), track("d", "Smooth Criminal", "Aubrey Logan")]
    links = {"smooth criminal ~ michael jackson": "w1", "smooth criminal ~ david garrett": "w1", "smooth criminal ~ 2 cellos": "w1"}
    rows, works, _ = resolve_works(tracks, routines, [], links)
    key = {r["routine_id"]: (r["work_key"], r["same_title"]) for r in rows}
    assert key["a"] == key["b"] == key["c"] == ("smooth criminal", "joined_by_musicbrainz")
    assert key["d"] == ("smooth criminal ~ aubrey logan", "split_by_credit")  # no evidence: stays apart
    assert next(w for w in works if w["work_key"] == "smooth criminal")["n_versions"] == 3


def test_owner_joins_from_the_review_sheet_and_a_title_that_becomes_one_work_gets_the_plain_key():
    routines = {k: {"gymnast_page": k.upper(), "year": "2020"} for k in "abc"}
    tracks = [track("a", "Caruso", "Lara Fabian"), track("b", "Caruso", "Filippa Giordano"), track("c", "Caruso", "Benedetta Caretta")]
    joins = {"caruso ~ filippa giordano": "caruso ~ lara fabian", "caruso ~ benedetta caretta": "caruso ~ lara fabian"}
    rows, works, _ = resolve_works(tracks, routines, [], {}, joins)
    assert {r["work_key"] for r in rows} == {"caruso"} and works[0]["n_versions"] == 3
    assert [r["same_title"] for r in rows] == ["split_by_credit", "joined_by_owner", "joined_by_owner"]


def test_several_cuts_of_one_song_in_one_routine_are_one_medley_version():
    routines = {"a": {"gymnast_page": "A", "year": "2026"}}
    tracks = [{**track("a", "Pump up the Jam (Club Mix)", "Bodybangers"), "track_no": "1"},
              {**track("a", "Pump up the Jam", "Crazy Frog"), "track_no": "2"}]
    rows, works, _ = resolve_works(tracks, routines, [], {"pump up the jam ~ bodybangers": "w", "pump up the jam ~ crazy frog": "w"})
    assert {(r["work_key"], r["performer"], r["version_type"]) for r in rows} == {("pump up the jam", "Bodybangers / Crazy Frog", "medley")}
    assert works[0]["n_versions"] == 1
