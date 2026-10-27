from rg_music.mb_works import fill_from_work_recordings, find_evidence, main_name, matching_recordings, proposals, same_name


def work(wid, title, *writers):
    return {"id": wid, "title": title, "score": 100, "relations": [{"type": "composer", "artist": {"name": n}} for n in writers]}


def rec(rid, title, artist, score=100):
    return {"id": rid, "title": title, "score": score, "artist-credit": [{"name": artist}]}


def group(credit, title="Feeling Good", key=None):
    return {"title_cluster": "feeling good", "work_key": key or f"feeling good ~ {credit.lower()}", "title": title,
            "credit": credit, "n_gymnasts": 1}


def fake(recordings, links):
    def fetch(url, params, key):
        if key.startswith("search|"):
            return {"recordings": recordings}
        return {"relations": [{"type": "performance", "work": links[key[4:]]}]} if key[4:] in links else {}
    return fetch


def test_main_name_is_the_first_credited_name():
    assert main_name("Michel Camilo / Jorge Pardo") == "Michel Camilo"
    assert main_name("Calvin Harris feat Rihanna") == "Calvin Harris"


def test_a_recording_needs_the_same_title_and_a_shared_name():
    recs = [rec("a", "Feeling Good (Live)", "Muse"), rec("b", "Feeling Good", "Nina Simone"), rec("c", "Feeling Good", "Muse", 50)]
    assert [r["id"] for r in matching_recordings("feeling good", "Muse", recs)] == ["a"]


def test_recording_evidence_gives_the_work_the_recording_performs():
    fetch = fake([rec("r1", "Feeling Good", "Muse")], {"r1": work("w1", "Feeling Good")})
    got = find_evidence(group("Muse"), fetch, lambda title: [work("w1", "Feeling Good", "Anthony Newley", "Leslie Bricusse")])
    assert (got["evidence"], got["mb_work_id"], got["mb_writers"]) == ("recording", "w1", "Anthony Newley / Leslie Bricusse")


def test_a_credit_that_names_the_author_of_the_work_is_evidence_too():
    got = find_evidence(group("Consuelo Velázquez", "Besame Mucho") | {"title_cluster": "besame mucho"}, fake([], {}),
                        lambda title: [work("w9", "Bésame mucho", "Consuelo Velázquez")])
    assert (got["evidence"], got["mb_work_id"]) == ("credited_author", "w9")


def test_no_credit_or_nothing_found_is_none():
    assert find_evidence(group(""), fake([], {}), lambda t: [])["evidence"] == "none"
    assert find_evidence(group("Otyken", "Storm"), fake([rec("x", "Storm", "Someone Else")], {}), lambda t: [])["evidence"] == "none"


def test_groups_with_one_musicbrainz_work_are_proposed_as_one():
    links = [{"title_cluster": "t", "work_key": k, "mb_work_id": w} for k, w in
             [("t ~ a", "w1"), ("t ~ b", "w1"), ("t ~ c", "w2"), ("t ~ d", "")]]
    (p,) = proposals(links)
    assert (p["proposal"], p["joined"], p["apart"], p["not_found"]) == ("join", "t ~ a + t ~ b", "t ~ c", "t ~ d")


def test_a_shared_first_name_is_not_the_same_performer():
    assert not same_name("Michael Bublé", "Michael Jackson")
    assert same_name("Jay Hawkins", "Screamin’ Jay Hawkins") and same_name("2 Cellos", "2CELLOS")
    assert [r["id"] for r in matching_recordings("feeling good", "Michael Bublé", [rec("x", "Feeling Good", "Michael Jackson")])] == []


def test_second_pass_finds_a_cover_among_the_recordings_of_the_work():
    links = [{"title_cluster": "smooth criminal", "work_key": "smooth criminal ~ michael jackson", "title": "Smooth Criminal",
              "credit": "Michael Jackson", "evidence": "credited_author", "mb_work_id": "w1", "mb_work_title": "Smooth Criminal",
              "mb_writers": "Michael Jackson"},
             {"title_cluster": "smooth criminal", "work_key": "smooth criminal ~ david garrett", "title": "Smooth Criminal",
              "credit": "David Garrett", "evidence": "none", "mb_work_id": "", "mb_work_title": "", "mb_writers": ""},
             {"title_cluster": "smooth criminal", "work_key": "smooth criminal ~ aubrey logan", "title": "Smooth Criminal",
              "credit": "Aubrey Logan", "evidence": "none", "mb_work_id": "", "mb_work_title": "", "mb_writers": ""}]
    work_lookup = {"relations": [{"recording": {"artist-credit": [{"name": n}]}} for n in ("Michael Jackson", "David Garrett")]}
    fill_from_work_recordings(links, lambda url, params, key: work_lookup if key == "work|w1" else {}, lambda title: [])
    assert [(x["evidence"], x["mb_work_id"]) for x in links[1:]] == [("work_recording", "w1"), ("none", "")]


def test_get_json_retries_a_dropped_connection():
    import requests
    from rg_music.mb_works import get_json

    class Ok:
        status_code = 200
        headers = {}
        def raise_for_status(self): pass
        def json(self): return {"works": []}

    calls = []
    def get(url, **kw):
        calls.append(url)
        if len(calls) == 1:
            raise requests.ConnectionError("reset by peer")
        return Ok()
    cache = {}
    assert get_json("u", {}, cache, "k", get, "ua", sleep=lambda s: None) == {"works": []}
    assert len(calls) == 2 and cache["k"] == {"works": []}
