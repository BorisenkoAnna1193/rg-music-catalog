from rg_music.worlds import (
    Appearance, aggregate, championship_pages, extract_appearances, name_key,
)

FLAT = """
<h2>Individual</h2><h3>Qualification</h3>
<table class="wikitable">
<tr><th>Rank</th><th>Gymnast</th><th>Nation</th><th>Total</th></tr>
<tr><th>1</th><td><a href="/wiki/Stiliana_Nikolova" title="x">Stiliana Nikolova</a></td>
    <td><span class="flagicon"><img src="//x/Flag_of_Bulgaria.svg.png"></span><a href="/wiki/Bulgaria">Bulgaria</a></td><td>104.3</td></tr>
<tr><th>2</th><td>Eva Ericson^</td><td><a href="/wiki/Sweden">Sweden</a></td><td>90</td></tr>
<tr><th>3</th><td>Other non-Team</td><td><a href="/wiki/Angola">Angola</a></td><td>1</td></tr>
</table>
<h3>All-Around Final</h3>
<table class="wikitable">
<tr><th>Rank</th><th>Gymnast</th><th>Nation</th></tr>
<tr><th></th><td><a href="/wiki/Stiliana_Nikolova">Stiliana Nikolova</a></td><td><a href="/wiki/Bulgaria">Bulgaria</a></td></tr>
</table>
<h3>Group All-Around</h3>
<table class="wikitable"><tr><th>Place</th><th>Nation</th><th>5</th></tr><tr><td>1</td><td>Israel</td><td>38</td></tr></table>
"""

TEAM_LAYOUT = """
<h3>Teams Competition and Individual Qualification</h3>
<table class="wikitable">
<tr><th>Nation/Gymnasts</th><th>Hoop</th><th>Total</th></tr>
<tr><td><b><span class="flagicon"><img src="//x/Flag_of_Russia.svg.png"></span><a href="/wiki/Russia">Russia</a></b></td><td>37</td><td>149</td></tr>
<tr><td><a href="/wiki/Yana_Kudryavtseva">Yana Kudryavtseva</a></td><td>18</td><td>(1)</td></tr>
<tr><td>Basma Ouatay ( MAR )</td><td>12</td><td>37</td></tr>
<tr><td>Elyane Boal ( CPV )</td><td>9</td><td>27</td></tr>
</table>
"""


def test_flat_tables_give_qualification_and_final_only():
    apps, used = extract_appearances(FLAT, 2023, "u")
    assert [(a.stage, a.name, a.nation) for a in apps] == [
        ("qualification", "Stiliana Nikolova", "Bulgaria"),
        ("qualification", "Eva Ericson", "Sweden"),      # trailing ^ removed, placeholder row dropped
        ("all-around", "Stiliana Nikolova", "Bulgaria"),
    ]
    assert apps[0].wiki_title == "Stiliana Nikolova" and apps[1].wiki_title == ""
    assert len(used) == 2  # the group table has no Name column


def test_team_layout_takes_country_from_team_row_and_code_for_individuals():
    apps, _ = extract_appearances(TEAM_LAYOUT, 2015, "u")
    assert [(a.name, a.nation) for a in apps] == [
        ("Yana Kudryavtseva", "Russia"), ("Basma Ouatay", "MAR"),
        ("Elyane Boal", "CPV"),
    ]


def test_name_key_ignores_transliteration_and_order():
    assert name_key("Yevgeniya Kanayeva") == name_key("Evgeniya Kanaeva")
    assert name_key("Seo Goeun") == name_key("Goeun Seo")
    assert name_key("Eliza Białkowska") == name_key("Eliza Bialkowska")
    assert name_key("Anna Bessonova") != name_key("Anna Besedina")


def _app(year, name, link, nation):
    return Appearance(year, "all-around", name, link, nation, "h", "u")


def test_same_page_different_spellings_is_one_gymnast_and_unlinked_year_is_merged():
    resolved = {"Evgeniya Kanaeva": ("Evgeniya Kanaeva", 7), "Evgenia Kanaeva": ("Evgeniya Kanaeva", 7)}
    rows = aggregate([
        _app(2009, "Yevgeniya Kanayeva", "Evgeniya Kanaeva", "Russia"),
        _app(2011, "Evgenia Kanaeva", "Evgenia Kanaeva", "Russia"),
        _app(2007, "Evgeniya Kanaeva", "", "Russia"),          # no link in that year's table
        _app(2007, "Evgeniya Kanaeva", "", "Ukraine"),         # same name, other country: not merged
    ], resolved)
    assert len(rows) == 2
    linked = next(r for r in rows if r["has_page"])
    assert linked["years"] == "2007,2009,2011" and linked["n_spellings"] == 3 and linked["merged_by_name"]


def test_championship_pages_skip_red_links():
    html = """<table class="wikitable"><tr><th>Year</th><th>Games</th></tr>
    <tr><td>2023</td><td><a href="/wiki/2023_Rhythmic_Gymnastics_World_Championships">40th</a></td></tr>
    <tr><td>2027</td><td><a href="/w/index.php?title=2027_Rhythmic_Gymnastics_World_Championships&redlink=1">x</a></td></tr></table>"""
    assert championship_pages(html) == [(2023, "2023 Rhythmic Gymnastics World Championships")]
