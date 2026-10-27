from rg_music.name_decisions import wiki_order
from rg_music.wg_names import letters, propose


def bio(i, last, first, code):
    return {"id": str(i), "preferredlastname": last, "preferredfirstname": first, "code": code, "gymnaststatus": "retired"}


def gym(name, country, spellings=""):
    return {"canonical_name": name, "country_id": country, "years": "2020", "events": "world 2020", "wiki_page": "",
            "name_source": "table", "spellings": spellings or name, "gymnast_keys": "page:" + name}


def test_only_a_real_difference_in_letters_is_proposed():
    bios = [bio(1, "LEWINSKA", "Liliana", "POL"), bio(2, "SON", "Yeon Jae", "KOR"), bio(3, "GODUNKO", "Nataliia", "UKR"),
            bio(4, "PETROVA", "Anna", "BUL"), bio(5, "PETROVA", "Anna", "BUL")]
    rows = propose([gym("Liliana Lewińska", "POL"), gym("Son Yeon-jae", "KOR"), gym("Natalia Godunko", "UKR"),
                    gym("Anna Petrova", "BGR"), gym("Nobody Here", "FRA")], bios)
    assert [(r["proposed_name"], r["change"], r["match"]) for r in rows] == [
        ("Liliana Lewińska", "", "name+country"),     # accents only: the Wikipedia spelling stays
        ("Son Yeon-jae", "", "name+country"),          # hyphen and word order only
        ("Nataliia Godunko", "yes", "name+country"),   # a real difference: official spelling
        ("Anna Petrova", "", "ambiguous"),             # two biographies: nothing proposed
        ("Nobody Here", "", "not_found"),
    ]


def test_letters_and_wiki_order():
    assert letters("Son Yeon-jae") == letters("Yeon Jae Son")
    assert letters("Celeste D'Arcangelo") == letters("D Celeste Arcangelo")
    assert wiki_order("Ling Zhong", "Zhong Ling") == "Zhong Ling"
    assert wiki_order("Nataliia Godunko", "Natalia Godunko") == "Nataliia Godunko"  # other words: unchanged


def test_owner_decisions_rename_only_accepted_and_still_matching_rows():
    from rg_music.name_decisions import apply_wg_decisions
    final = [{"canonical_name": "Natalia Godunko", "name_source": "table", "gymnast_keys": "page:1"},
             {"canonical_name": "Viktoria Bengtsson", "name_source": "table", "gymnast_keys": "name:x|SWE"},
             {"canonical_name": "Renamed Since", "name_source": "table", "gymnast_keys": "page:3"}]
    decisions = [{"gymnast_key": "page:1", "name_before": "Natalia Godunko", "name_after": "Nataliia Godunko", "decision": "accept"},
                 {"gymnast_key": "name:x|SWE", "name_before": "Viktoria Bengtsson", "name_after": "Viktoria Bengtsonn", "decision": "reject"},
                 {"gymnast_key": "page:3", "name_before": "Old Name", "name_after": "New Name", "decision": "accept"}]
    unused = apply_wg_decisions(final, decisions)
    assert [(r["canonical_name"], r["name_source"]) for r in final] == [
        ("Nataliia Godunko", "world_gymnastics"), ("Viktoria Bengtsson", "table"), ("Renamed Since", "table")]
    assert [d["name_before"] for d in unused] == ["Old Name"]  # stale: reported, not applied
