"""Parser tests on small HTML fixtures that mimic layouts seen on real pages."""

from rg_music.tables import classify, extract_music_tables

# Year with rowspan (Averina style), a footnote, an empty music cell.
ROWSPAN = """
<table class="wikitable">
<tr><th>Year</th><th>Apparatus</th><th>Music title</th></tr>
<tr><td rowspan="3">2023</td><td>Hoop</td>
    <td>"Butterflies and Hurricanes" by <a href="#">Muse</a><sup class="reference">[12]</sup></td></tr>
<tr><td>Ball</td><td>"Toxic" by 2WEI</td></tr>
<tr><td>Ribbon</td><td></td></tr>
<tr><td rowspan="2">2022</td><td>Ball (first)</td><td>"So Far" by Ólafur&nbsp;Arnalds</td></tr>
<tr><td>Clubs</td><td>Track one<br>Track two</td></tr>
</table>
"""

# Year as a header cell alone in its own row, spanning the rows below it
# (Kaleyn / Harnasko style).
YEAR_OWN_ROW_ROWSPAN = """
<table class="wikitable">
<tr><th>Year</th><th>Apparatus</th><th>Music title</th></tr>
<tr><th rowspan="3">2024</th></tr>
<tr><td>Hoop</td><td>"S-Class" by Stray Kids</td></tr>
<tr><td>Ball</td><td>"Never Enough" by Loren Allred</td></tr>
<tr><td>2023</td><td>Hoop</td><td>"Boryano, Balgarko" by Emelina Gorcheva</td></tr>
</table>
"""

# Year alone in a row WITHOUT rowspan: following rows are one cell short.
YEAR_OWN_ROW_PLAIN = """
<table class="wikitable">
<tr><th>Year</th><th>Apparatus</th><th>Music title</th></tr>
<tr><td colspan="3">2025</td></tr>
<tr><td>Hoop</td><td>Black Heart by Jake Warren</td></tr>
<tr><td>Ball</td><td>La Última Curda by Yasmin Levy</td></tr>
</table>
"""

# Olympic results table: music column + competition column.
COMPETITION = """
<table class="wikitable">
<tr><th>Year</th><th>Competition Description</th><th>Location</th><th>Music</th>
    <th>Apparatus</th><th>Rank-Final</th></tr>
<tr><td rowspan="3">2020</td><td rowspan="3">Olympics</td><td rowspan="3">Tokyo</td>
    <td></td><td>All-around</td><td>2nd</td></tr>
<tr><td>"Thunderstruck" by David Garrett</td><td>Hoop</td><td>2nd</td></tr>
<tr><td>"FOGO" by Garmiani</td><td>Clubs</td><td>2nd</td></tr>
</table>
"""

NOT_MUSIC = """
<table class="wikitable">
<tr><th>Year</th><th>Event</th><th>AA</th><th>Hoop</th></tr>
<tr><td>2021</td><td>World Championships</td><td>1st</td><td>1st</td></tr>
</table>
"""


def _rows(html):
    return extract_music_tables(html)[1]


def test_rowspan_year_is_propagated():
    rows = _rows(ROWSPAN)
    assert [(r.year, r.apparatus) for r in rows] == [
        ("2023", "Hoop"), ("2023", "Ball"), ("2023", "Ribbon"),
        ("2022", "Ball (first)"), ("2022", "Clubs"),
    ]


def test_cell_cleanup():
    rows = _rows(ROWSPAN)
    assert rows[0].music == '"Butterflies and Hurricanes" by Muse'  # footnote gone
    assert rows[3].music == '"So Far" by Ólafur Arnalds'  # nbsp -> space
    assert rows[4].music == "Track one | Track two"  # <br> kept as a separator


def test_empty_music_is_kept_and_flagged():
    ribbon = _rows(ROWSPAN)[2]
    assert ribbon.music == "" and "music_empty" in ribbon.notes


def test_year_in_own_row_with_rowspan():
    rows = _rows(YEAR_OWN_ROW_ROWSPAN)
    assert [(r.year, r.apparatus) for r in rows] == [
        ("2024", "Hoop"), ("2024", "Ball"), ("2023", "Hoop"),
    ]


def test_year_in_own_row_without_rowspan():
    rows = _rows(YEAR_OWN_ROW_PLAIN)
    assert [(r.year, r.apparatus) for r in rows] == [("2025", "Hoop"), ("2025", "Ball")]
    assert all("year_carried_over" in r.notes for r in rows)


def test_competition_table():
    rows = _rows(COMPETITION)
    assert {r.table_kind for r in rows} == {"competition"}
    hoop = next(r for r in rows if r.apparatus == "Hoop")
    assert (hoop.year, hoop.competition, hoop.location) == ("2020", "Olympics", "Tokyo")
    assert hoop.music == '"Thunderstruck" by David Garrett'


def test_results_table_is_ignored():
    infos, rows = extract_music_tables(NOT_MUSIC)
    assert rows == [] and infos[0].kind == "other"


def test_classify_header_variants():
    assert classify(["Year", "Apparatus", "Music Title"]) == "routine"
    assert classify(["Year", "Apparatus", "Music title"]) == "routine"
    assert classify(["Year", "Competition Description", "Location", "Music", "Apparatus"]) == "competition"
