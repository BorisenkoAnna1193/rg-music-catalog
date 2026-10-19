from rg_music.merge import merge_native
from rg_music.native_extract import native_rows, split_year, translate_apparatus

SPANISH_TABLE = """
<table class="wikitable"><tr><th>Año</th><th>Aparatos</th><th>Música</th></tr>
<tr><td>1994 (Individual júnior)</td><td>Manos libres</td><td>«Padam… padam…» de Édith Piaf.</td></tr>
<tr><td>1995-1996</td><td>Cinta</td><td>«Boda en Sarajevo».</td></tr>
</table>
<table class="nowraplinks navbox-inner"><tr><th>Música</th><th>Música</th></tr><tr><td>a</td><td>b</td></tr></table>
"""


def native(year, apparatus, music, lang="es", row=0):
    return {"gymnast_page": "A B", "lang": lang, "table_index": "0", "row_index": str(row), "year": year,
            "apparatus": apparatus, "music": music, "source_url": "u", "revid": "1"}


def english(year, apparatus, music):
    return {"gymnast_page": "A B", "year": year, "apparatus": apparatus, "music": music}


def test_only_wikitables_with_year_apparatus_and_music_headers_are_read():
    rows = native_rows(SPANISH_TABLE, "es")
    assert [(r["year"], r["apparatus"], r["music"]) for r in rows] == [
        ("1994 (Individual júnior)", "Manos libres", "«Padam… padam…» de Édith Piaf."),
        ("1995-1996", "Cinta", "«Boda en Sarajevo»."),
    ]


def test_year_keeps_the_season_and_the_category_apart():
    assert split_year("1994 (Individual júnior)") == ("1994", "junior")
    assert split_year("2001 - 2002") == ("2001-2002", "")
    assert split_year("2007 (categoría alevín)") == ("2007", "pre-junior")
    assert split_year("1989 (Conjunto 1.ª categoría)").category == "group"


def test_apparatus_is_translated_and_groups_are_marked():
    assert translate_apparatus("Aro", "es") == ("Hoop", "individual")
    assert translate_apparatus("Cinta (Inicio de temporada)", "es").text == "Ribbon (start of season)"
    assert translate_apparatus("Cinta (JJ. OO. de Sídney)", "es").text == "Ribbon (Sydney 2000 Olympics)"
    assert translate_apparatus("Ejercicio de exhibición (Manos libres, cinta) junto a X en Euskalgym", "es").text == \
        "Gala (Free hands, Ribbon; with X at Euskalgym)"
    assert translate_apparatus("Ejercicio de exhibición (Manos libres) junto a A, B, C y D en Euskalgym", "es").text == \
        "Gala (Free hands; with A, B and others at Euskalgym)"
    assert translate_apparatus("3 aros y 2 pelotas", "es").kind == "group"
    assert translate_apparatus("Мяч (вторая версия)", "ru").text == "Ball (second)"
    assert translate_apparatus("Gala (Grand Prix Moscow opening)", "ru").text == "Gala (Grand Prix Moscow opening)"
    assert translate_apparatus("Trampolín", "es").kind == "unknown"


def test_native_row_fills_a_gap_with_the_english_wording():
    added, todo, stats = merge_native([], [native("1994 (Individual júnior)", "Aro", "«Hero» de Mariah Carey.")],
                                      {("es", "«Hero» de Mariah Carey."): "Hero by Mariah Carey"})
    (row,) = added
    assert (row["routine_id"], row["year"], row["apparatus"], row["music"], row["source"]) == \
           ("A B|es0|0", 1994, "Hoop", "Hero by Mariah Carey", "native_wiki_es")
    assert row["notes"] == "translated_from_es;category_junior" and not todo


def test_season_is_expanded_and_a_year_the_english_article_has_is_not_added_twice():
    added, _, stats = merge_native([english(2001, "Hoop", "Hero by Mariah Carey")],
                                   [native("2000 - 2001", "Aro", "«Hero» de Mariah Carey.")],
                                   {("es", "«Hero» de Mariah Carey."): "Hero by Mariah Carey"})
    assert [(r["routine_id"], r["year"], r["year_source"]) for r in added] == [("A B|es0|0#2000", 2000, "2000-2001")]
    assert stats["native_rows_same_as_english"] == 1


def test_other_music_in_the_same_year_is_added_and_flagged():
    added, _, stats = merge_native([english(2005, "Ribbon", "Caravan by Michel Camilo")],
                                   [native("2005", "Cinta", "«Montserrat» de Bajofondo Tango Club.")],
                                   {("es", "«Montserrat» de Bajofondo Tango Club."): "Montserrat by Bajofondo Tango Club"})
    assert "differs_from_english_article" in added[0]["notes"] and stats["native_rows_added_with_conflict"] == 1


def test_untranslated_cells_are_listed_not_merged_and_groups_and_unknown_music_are_skipped():
    added, todo, stats = merge_native([], [native("2003", "Pelota", "«Tojojo» de Øystein Sevåg."),
                                           native("2004", "5 cintas", "x"), native("1982", "Aro", "Desconocida.")], {})
    assert not added and [t["reason"] for t in todo] == ["new"]
    assert stats["native_group_rows_skipped"] == 1 and stats["native_rows_without_music"] == 1


def test_without_a_translation_an_english_title_inside_the_native_text_is_the_same_music():
    _, todo, stats = merge_native([english(2015, "Ball", "Boléro by Maurice Ravel")],
                                  [native("2015", "Мяч", "Boléro — Морис Равель", lang="ru")], {})
    assert stats["native_rows_same_as_english"] == 1 and not todo


def test_russian_rows_are_not_compared_with_other_english_music():
    added, todo, stats = merge_native([english(2015, "Ball", "Boléro by Maurice Ravel")],
                                      [native("2015", "Мяч", "Болеро — Морис Равель", lang="ru")], {})
    assert not added and not todo and stats["native_rows_not_compared"] == 1


def test_owner_decisions_on_conflicts_keep_both_drop_native_or_drop_english():
    pool = [{**english(2005, "Ribbon", "Caravan by Michel Camilo"), "routine_id": "en1"},
            {**english(2005, "Clubs", "Por ti by Ruben Moran"), "routine_id": "en2"},
            {**english(2003, "Clubs", "Pistolero by Juno Reactor"), "routine_id": "en3"}]
    rows = [native("2005", "Cinta", "«Montserrat».", row=0), native("2005", "Mazas", "«Conte».", row=1),
            native("2003", "Mazas", "«Quixote».", row=2)]
    tr = {("es", "«Montserrat»."): "Montserrat by Bajofondo", ("es", "«Conte»."): "Conte d'Amour by Zbigniew Preisner",
          ("es", "«Quixote»."): "Quixote by Bond"}
    decisions = {"A B|es0|0": {"decision": "english"}, "A B|es0|1": {"decision": "spanish", "english_routine_ids": "en2"},
                 "A B|es0|2": {"decision": "both"}}
    added, _, stats = merge_native(pool, rows, tr, decisions)
    assert [(r["routine_id"], r["notes"].split(";")[-1]) for r in added] == [
        ("A B|es0|1", "chosen_by_owner_over_english"), ("A B|es0|2", "kept_both_by_owner")]
    assert stats["dropped_english"] == ["en2"] and stats["native_rows_rejected_by_owner"] == 1
