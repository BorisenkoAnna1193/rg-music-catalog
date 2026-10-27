from rg_music.continental import championship_titles, extract, section_path
from rg_music.countries import load_reference

from bs4 import BeautifulSoup

REF = load_reference()

MEDALS = """
<h2>Medal winners</h2>
<table class="wikitable">
<tr><th>Event</th><th>Gold</th><th>Silver</th><th>Bronze</th></tr>
<tr><th colspan="4">Team Competition</th></tr>
<tr><td>Team</td><td><b><a href="/wiki/Bulgaria" title="Bulgaria">Bulgaria</a></b><br><a href="/wiki/A_B" title="A B">A B</a></td><td>x</td><td>y</td></tr>
<tr><th colspan="4">Senior Individual</th></tr>
<tr><td>All-Around <a href="#r">details</a></td>
    <td><b><a href="/wiki/Galina_Shugurova" title="Galina Shugurova">Galina Shugurova</a></b><br><span class="flagicon"><img src="//x/Flag_of_the_Soviet_Union.svg.png"></span><a href="/wiki/Soviet_Union" title="Soviet Union">Soviet Union</a></td>
    <td><span class="flagicon"><img src="//x/Flag_of_South_Africa.svg.png"></span><a href="/wiki/Grace_Legote" title="Grace Legote">Grace Legote</a> (<abbr title="South Africa">RSA</abbr>)</td>
    <td>Haya Zayed ( EGY )</td></tr>
<tr><td>Clubs</td><td><a href="/w/index.php?title=Anna_Chichova&amp;redlink=1" class="new" title="Anna Chichova (page does not exist)">Anna Chichova</a> (<abbr>RUS</abbr>)</td><td>None awarded</td><td>Haya Zayed ( EGY )</td></tr>
<tr><th colspan="4">Junior Individual</th></tr>
<tr><td>Rope</td><td>Little One ( RUS )</td><td>b</td><td>c</td></tr>
<tr><th colspan="4">Senior Groups</th></tr>
<tr><td>5 Hoops</td><td><a href="/wiki/Russia" title="Russia">Russia</a></td><td>b</td><td>c</td></tr>
</table>
"""


def test_medal_table_keeps_senior_individual_events_only():
    apps, info = extract(MEDALS, "1978 Rhythmic Gymnastics European Championships", 1978, "u", "europe", REF)
    assert [(a.name, a.wiki_title, a.nation, a.event, a.stage) for a in apps] == [
        ("Galina Shugurova", "Galina Shugurova", "Soviet Union", "All-Around", "medal"),   # 'details' link dropped
        ("Grace Legote", "Grace Legote", "RSA", "All-Around", "medal"),
        ("Haya Zayed", "", "EGY", "All-Around", "medal"),                                 # name without a link
        ("Anna Chichova", "", "RUS", "Clubs", "medal"),                                   # red link: no article
        ("Haya Zayed", "", "EGY", "Clubs", "medal"),                                      # 'None awarded' skipped
    ]
    assert all(a.competition == "europe" for a in apps)
    assert any("Junior Individual" in s for s in info["skipped_events"])


GENERAL = """
<h2>Artistic gymnastics</h2>
<table class="wikitable"><tr><th>Event</th><th>Gold</th><th>Silver</th><th>Bronze</th></tr>
<tr><td>Individual all-around</td><td>Abel Drigg ( CUB )</td><td>a b</td><td>c d</td></tr></table>
<h2>Rhythmic gymnastics</h2>
<table class="wikitable"><tr><th>Event</th><th>Gold</th><th>Silver</th><th>Bronze</th></tr>
<tr><td>Individual all-around</td><td>Olga Karmansky ( USA )</td><td>Cynthia Valdez ( MEX )</td><td>Ana Paula Ribeiro ( BRA )</td></tr></table>
"""


def test_general_championship_reads_only_the_rhythmic_section():
    apps, _ = extract(GENERAL, "2005 Pan American Gymnastics Championships", 2005, "u", "panam", REF)
    assert [a.name for a in apps] == ["Olga Karmansky", "Cynthia Valdez", "Ana Paula Ribeiro"]


FULL = """
<h2>Results</h2><h3>Senior</h3><h4>All-Around</h4>
<table class="wikitable"><tr><th>Rank</th><th>Gymnast</th><th>Nation</th></tr>
<tr><td>1</td><td><a href="/wiki/Sofia_Raffaeli">Sofia Raffaeli</a></td><td><a href="/wiki/Italy">Italy</a></td></tr></table>
<h4>Hoop</h4>
<table class="wikitable"><tr><th>Rank</th><th>Gymnast</th><th>Nation</th></tr>
<tr><td>5</td><td><a href="/wiki/Lala_Kramarenko">Lala Kramarenko</a></td><td><a href="/wiki/Russia">Russia</a></td></tr></table>
<h3>Junior</h3><h4>All-Around</h4>
<table class="wikitable"><tr><th>Rank</th><th>Gymnast</th><th>Nation</th></tr>
<tr><td>1</td><td>Kid Gymnast</td><td><a href="/wiki/Italy">Italy</a></td></tr></table>
"""


def test_full_tables_take_finals_and_skip_the_junior_section():
    apps, info = extract(FULL, "2023 Pan American Rhythmic Gymnastics Championships", 2023, "u", "panam", REF)
    assert [(a.name, a.stage) for a in apps] == [("Sofia Raffaeli", "all-around"), ("Lala Kramarenko", "final")]
    soup = BeautifulSoup(FULL, "lxml")
    assert section_path(soup.select("table")[2]) == ["Results", "Junior", "All-Around"]


def test_index_titles_match_the_pattern_only():
    html = ('<a href="/wiki/2018_Rhythmic_Gymnastics_European_Championships">x</a>'
            '<a href="/wiki/2018_European_Championships">multi-sport</a>'
            '<a href="/wiki/2019_Junior_Rhythmic_Gymnastics_European_Championships">j</a>')
    assert championship_titles(html, r"\d{4} Rhythmic Gymnastics European Championships") == [
        (2018, "2018 Rhythmic Gymnastics European Championships")]


TIE = """
<h2>Medal winners</h2>
<table class="wikitable"><tr><th>Event</th><th>Gold</th><th>Silver</th><th>Bronze</th></tr>
<tr><th>All-Around</th>
<td><b><a href="/wiki/Adriana_Dunavska" title="Adriana Dunavska">Adriana Dunavska</a></b><br><span class="flagicon"><img src="//x/Flag_of_Bulgaria.svg.png"></span><a href="/wiki/Bulgaria" title="Bulgaria">Bulgaria</a><br>
    <b><a href="/wiki/Alexandra_Timoshenko" title="Alexandra Timoshenko">Alexandra Timochenko</a></b><br><span class="flagicon"><img src="//x/Flag_of_the_Soviet_Union.svg.png"></span><a href="/wiki/Soviet_Union" title="Soviet Union">Soviet Union</a></td>
<td><span class="flagicon"><img src="//x/Flag_of_Japan.svg.png"></span><a href="/wiki/A_One" title="A One">A One</a><br><span class="flagicon"><img src="//x/Flag_of_China.svg.png"></span><a href="/wiki/B_Two" title="B Two">B Two</a></td>
<td>x</td></tr></table>
"""


def test_a_tie_gives_every_medalist_her_own_country():
    apps, _ = extract(TIE, "1988 Rhythmic Gymnastics European Championships", 1988, "u", "europe", REF)
    assert [(a.name, a.nation) for a in apps] == [
        ("Adriana Dunavska", "Bulgaria"), ("Alexandra Timochenko", "Soviet Union"),
        ("A One", "Japan"), ("B Two", "China"),   # bare flags before the names
    ]
