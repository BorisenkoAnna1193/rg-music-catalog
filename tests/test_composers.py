from rg_music import composers
from rg_music.composers import choose, composers_of, search


def cand(title, score, *people, mbid="id"):
    return {"id": mbid, "title": title, "score": score,
            "relations": [{"type": t, "artist": {"name": n}} for t, n in people]}


def test_composers_are_only_composer_and_writer_relations():
    c = cand("Caruso", 100, ("composer", "Lucio Dalla"), ("lyricist", "Lucio Dalla"), ("arranger", "X"), ("writer", "Y"))
    assert composers_of(c) == ["Lucio Dalla", "Y"]


def test_high_when_a_composer_is_also_credited_in_our_data():
    got = choose("bolero", "Maurice Ravel (7) | Prequell (3)",
                 [cand("Boléro", 100, ("composer", "Joseph Maurice Ravel"), mbid="ravel"), cand("Bolero", 98, ("composer", "Other"))])
    assert (got["confidence"], got["mb_id"], got["composers"]) == ("high", "ravel", "Joseph Maurice Ravel")


def test_probable_when_one_candidate_has_exactly_that_title():
    got = choose("caruso", "Lara Fabian (2) | Luciano Pavarotti (2)",
                 [cand("Caruso", 100, ("composer", "Lucio Dalla")), cand("Caruso Dances", 83, ("composer", "Z"))])
    assert (got["confidence"], got["composers"]) == ("probable", "Lucio Dalla")


def test_ambiguous_lists_the_alternatives_and_none_when_nothing_matches():
    got = choose("o fortuna", "Carl Orff (4)", [cand("O Fortuna", 100, ("composer", "Sel Balamir")), cand("O Fortuna", 98),
                                              cand("O Fortuna", 98, ("lyricist", "[anonymous]"))])
    assert got["confidence"] == "ambiguous" and got["composers"] == "Sel Balamir" and "(no composer)" in got["alternatives"]
    assert choose("zzz", "X", [cand("Something else", 100)])["confidence"] == "none"
    assert choose("low", "X", [cand("Low", 40)])["confidence"] == "none"


def test_search_is_cached_and_waits_between_requests():
    calls, naps = [], []

    class Resp:
        status_code = 200
        headers = {}
        def raise_for_status(self): pass
        def json(self): return {"works": [cand("Caruso", 100)]}

    def get(url, **kw):
        calls.append(kw["params"]["query"])
        return Resp()

    cache = {}
    search("Caruso", cache, get, "ua", sleep=naps.append)
    search("Caruso", cache, get, "ua", sleep=naps.append)
    assert calls == ['work:"Caruso"'] and naps == [1.1]


def test_503_is_retried_after_a_longer_wait():
    naps, answers = [], []

    class Resp:
        def __init__(self, status): self.status_code, self.headers = status, {"Retry-After": "7"}
        def raise_for_status(self): pass
        def json(self): return {"works": [cand("Caruso", 100)]}

    queue = [Resp(503), Resp(503), Resp(200)]
    def get(url, **kw):
        answers.append(1)
        return queue.pop(0)

    cache = {}
    assert search("Caruso", cache, get, "ua", sleep=naps.append)[0]["title"] == "Caruso"
    assert len(answers) == 3 and 7.0 in naps
