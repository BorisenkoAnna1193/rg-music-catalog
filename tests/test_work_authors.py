from rg_music.work_authors import choose_work, from_title_hint, has_lyrics, import_sheet, propose


def mbw(wid, title, *writers, recordings=0, type_="Song", languages=("eng",), score=100):
    rels = [{"type": "composer", "artist": {"name": n}} for n in writers]
    rels += [{"type": "performance", "recording": {"id": str(i)}} for i in range(recordings)]
    return {"id": wid, "title": title, "score": score, "type": type_, "languages": list(languages), "relations": rels}


def work(classical="0", classical_composer="", composer=""):
    return {"is_classical": classical, "classical_composer": classical_composer, "composer": composer}


def test_a_work_is_chosen_by_a_credited_writer_then_alone_then_by_recordings():
    a, b = mbw("a", "Storm", "Otyken", recordings=1), mbw("b", "Storm", "Someone", recordings=9)
    assert choose_work("storm", ["Otyken"], [a, b], None) == (a, "credit")
    assert choose_work("storm", ["Havasi"], [a, b], None) == (b, "most_recorded")
    assert choose_work("storm", [], [a], None) == (a, "single")
    assert choose_work("storm", [], [mbw("c", "Stormy", score=100)], None) == (None, "none")
    assert choose_work("storm", [], [a], b)[1] == "known"


def test_lyrics_come_from_the_language():
    assert has_lyrics(mbw("a", "Boléro", languages=("zxx",))) == "no"
    assert has_lyrics(mbw("a", "Caruso", languages=("ita",))) == "yes"
    assert has_lyrics(mbw("a", "X", languages=())) == "" and has_lyrics(None) == ""


def test_proposal_follows_the_owner_rules():
    assert propose(work(), "folk music", [], ["Gopak"], None)[:2] == ("folk", "folk music")
    assert propose(work(), "", ["Ivan Larionov"], ["Kalinka (Russian folk)"], None)[0] == "folk"
    assert propose(work("1", "Maurice Ravel"), "", [], ["Boléro"], None)[:2] == ("composer", "Maurice Ravel")
    assert propose(work(), "Astor Piazzolla", [], ["Libertango"], None)[:2] == ("composer", "Astor Piazzolla")
    zorro = mbw("z", "The Mask of Zorro", "James Horner", type_="Soundtrack", languages=("zxx",))
    assert propose(work(), "", ["James Horner"], ["The Mask of Zorro"], zorro)[:2] == ("composer", "James Horner")
    song = mbw("s", "Feeling Good", "Anthony Newley", "Leslie Bricusse")
    assert propose(work(), "", ["Muse"], ["Feeling Good"], song)[:2] == ("performer", "")
    assert propose(work(), "", ["X"], ["Y"], None)[0] == "unknown"
    hava = mbw("h", "Hava Nagila", "[traditional]", "Abraham Zvi Idelsohn")
    assert propose(work(), "", ["André Rieu"], ["Hava Nagila"], hava)[0] == "folk"
    cosma = mbw("c", "Concerto de Berlin", "Vladimir Cosma", type_=None, languages=())
    assert propose(work(), "", ["Vladimir Cosma"], ["Concerto de Berlin"], cosma)[:2] == ("composer", "Vladimir Cosma")
    perhaps = mbw("p", "Perhaps, Perhaps, Perhaps", "Osvaldo Farrés", languages=())
    assert propose(work(), "", ["The Pussycat Dolls"], ["Perhaps"], perhaps)[0] == "performer"


def test_from_title_hint_guesses_the_kind():
    assert from_title_hint(["Mein Herr by Liza Minnelli (musical)"], ["Cabaret"]) == ("Cabaret", "musical")
    assert from_title_hint(["Feeling Good music from Origin of Symmetry by Muse"], ["Origin of Symmetry"]) == ("", "")
    assert from_title_hint(["Caravan (From the film Ocean's 13 (OST))"], ["the film Ocean's 13"]) == ("Ocean's 13", "film")
    assert from_title_hint(["Cleopatra OST by Trevor Jones"], ["Cleopatra", "Cleopatra", ""]) == ("Cleopatra", "film")
    assert from_title_hint(["Caruso by Lara Fabian"], ["", ""]) == ("", "")


def test_import_keeps_owner_changes_moves_performer_names_to_original_and_applies_corrections():
    def prop(i, key, at="unknown", author="", basis="not found"):
        return {"row_id": i, "work_key": key, "work": key.title(), "author_type": at, "author": author, "from_title": "",
                "from_type": "", "has_lyrics": "", "basis": basis, "owner_note": ""}
    proposals = [prop("1", "obsidian"), prop("2", "volare"), prop("3", "tsigany"), prop("4", "feeling good", "performer"),
                 prop("5", "bolero", "composer", "Maurice Ravel", "classical")]
    sheet = [{**proposals[0], "author_type": "performer", "author": "Audiomachine"},
             {**proposals[1], "author_type": "Performer", "owner_note": "original: Domenico Modugno"},
             {**proposals[2], "author_type": "Folk"}, proposals[3]]
    fixes = [{"work_key": "volare", "field": "from_title", "value": "X", "reason": "test"}]
    got = {r["work_key"]: r for r in import_sheet(sheet, proposals, fixes)}
    assert (got["obsidian"]["author"], got["obsidian"]["original_performer"], got["obsidian"]["source"]) == ("", "Audiomachine", "owner")
    assert (got["volare"]["author_type"], got["volare"]["original_performer"], got["volare"]["from_title"]) == ("performer", "Domenico Modugno", "X")
    assert (got["tsigany"]["author_type"], got["tsigany"]["author"]) == ("folk", "folk music")
    assert got["feeling good"]["source"] == "proposal" and got["bolero"]["source"] == "rule"
