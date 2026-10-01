from rg_music.music_parser import parse_music


def one(cell):
    kind, tracks = parse_music(cell)
    assert kind == "tracks" and len(tracks) == 1, tracks
    return tracks[0]


def test_plain_by():
    t = one("Durch den Monsun by Tokio Hotel")
    assert (t.title, t.artist, t.status) == ("Durch den Monsun", "Tokio Hotel", "ok")


def test_quoted_title_by():
    t = one('"Total Eclipse of the Heart" by Bonnie Tyler')
    assert (t.title, t.artist) == ("Total Eclipse of the Heart", "Bonnie Tyler")


def test_comma_before_by_kanaeva():
    t = one('"Jota Aragonesa", by Mikhail Glinka')
    assert (t.title, t.artist, t.status) == ("Jota Aragonesa", "Mikhail Glinka", "ok")


def test_as_composed_by():
    t = one("Symphony No. 6 in B minor, Op. 74 as composed by Pyotr Ilyich Tchaikovsky")
    assert t.title == "Symphony No. 6 in B minor, Op. 74"
    assert (t.artist, t.status) == ("Pyotr Ilyich Tchaikovsky", "ok")


def test_composed_by_then_by_performer():
    t = one('"Spartacus", composed by Aram Khachaturian by Royal Philharmonic Orchestra, Yuri Simonov')
    assert t.title == "Spartacus"
    assert t.artist == "Aram Khachaturian, Royal Philharmonic Orchestra, Yuri Simonov"


def test_composer_goes_first_in_artist_whatever_the_source_order():
    t = one('"Time, Forward!" by Vedernikov & Orchestra, composed by Georgy Sviridov')
    assert (t.title, t.artist) == ("Time, Forward!", "Georgy Sviridov, Vedernikov & Orchestra")


def test_from_in_parens_before_by():
    t = one('"Never Enough" (from The Greatest Showman) by Loren Allred')
    assert (t.title, t.work, t.artist) == ("Never Enough", "The Greatest Showman", "Loren Allred")


def test_unquoted_from_in_parens():
    t = one("Big Spender (from Sweet Charity) by Fosse Ensemble")
    assert (t.title, t.work) == ("Big Spender", "Sweet Charity")


def test_music_from():
    t = one("This Is Halloween music from The Nightmare Before Christmas by Danny Elfman")
    assert (t.title, t.work, t.artist) == ("This Is Halloween", "The Nightmare Before Christmas", "Danny Elfman")


def test_ost_in_parens():
    t = one('"Hey Pachuco" (The Mask OST), by Royal Crown Revue')
    assert (t.title, t.work, t.artist) == ("Hey Pachuco", "The Mask", "Royal Crown Revue")


def test_performed_by_in_parens():
    t = one('"L-O-V-E", by Nat King Cole (performed by Joss Stone)')
    assert (t.title, t.artist, t.performer) == ("L-O-V-E", "Nat King Cole", "Joss Stone")


def test_original_and_remix():
    t = one('"Poeta (remix)", original by Vicente Amigo, remix by Maxime Rodriguez')
    assert (t.title, t.artist, t.status) == ("Poeta (remix by Maxime Rodriguez)", "Vicente Amigo", "ok")


def test_trailing_note_is_kept_out_of_artist():
    t = one('"Enter Sandman" by New Orleans Band (the first part is from Mozart\'s Symphony No. 40)')
    assert t.artist == "New Orleans Band"
    assert t.notes == ["the first part is from Mozart's Symphony No. 40"]


def test_multiple_quoted_titles_share_credit():
    _, tracks = parse_music('"Двигаться", "Kick It (Remix)", "Breaking it Down" by Raim, Village Girls')
    assert [t.title for t in tracks] == ["Двигаться", "Kick It (Remix)", "Breaking it Down"]
    assert {t.artist for t in tracks} == {"Raim, Village Girls"}


def test_slash_with_two_credits_makes_two_tracks():
    _, tracks = parse_music("Whip by Arca / Seep by William Morris (Kings & Creatures)")
    assert [(t.title, t.artist) for t in tracks] == [("Whip", "Arca"), ("Seep", "William Morris")]


def test_slash_in_title_before_single_by_shares_credit():
    _, tracks = parse_music("Plaza of Execution / Leave No Witnesses music from The Mask of Zorro by James Horner")
    assert [t.title for t in tracks] == ["Plaza of Execution", "Leave No Witnesses"]
    assert {t.work for t in tracks} == {"The Mask of Zorro"}


def test_semicolon_separates_tracks():
    _, tracks = parse_music('"Picture of Dorian Gray", by Charlie Mole; "Catch the Falling Sky", by Immediate Music')
    assert [(t.title, t.artist) for t in tracks] == [
        ("Picture of Dorian Gray", "Charlie Mole"), ("Catch the Falling Sky", "Immediate Music"),
    ]


def test_slash_titles_are_paired_with_slash_credits():
    _, tracks = parse_music("Caravane / Der Bauch / Istikhbar by Radar / MC Sultan / Gnawa Diffusion")
    assert [(t.title, t.artist) for t in tracks] == [
        ("Caravane", "Radar"), ("Der Bauch", "MC Sultan"), ("Istikhbar", "Gnawa Diffusion"),
    ]
    assert all("slash_split" in t.flags and t.status == "ok" for t in tracks)


def test_slash_inside_quotes_is_split_when_credits_match():
    _, tracks = parse_music('"Ritmo de Bom Bom/Samba Vocalizado" by Jubaba/Luciano Perrone')
    assert [(t.title, t.artist) for t in tracks] == [
        ("Ritmo de Bom Bom", "Jubaba"), ("Samba Vocalizado", "Luciano Perrone"),
    ]


def test_unpaired_slashes_need_review():
    _, tracks = parse_music("Andalucia / Taliquete by A / B / C")
    assert len(tracks) == 2 and all(t.status == "partial" for t in tracks)
    assert tracks[0].artist == "A / B / C"


def test_quoted_title_with_comma_artist_no_by():
    t = one('"Carmen Suite", Rodion Shchedrin')
    assert (t.title, t.artist, t.status) == ("Carmen Suite", "Rodion Shchedrin", "ok")
    assert "credit_without_by" in t.flags


def test_no_credit_is_partial():
    t = one("Russian Folk")
    assert (t.title, t.status, t.flags) == ("Russian Folk", "partial", ["no_credit"])


def test_unquoted_comma_list_is_flagged_not_split():
    t = one("Jackseye's Tale, Escape from East Berlin, Take You Down by Daniel Pemberton")
    assert t.title == "Jackseye's Tale, Escape from East Berlin, Take You Down"
    assert (t.flags, t.status) == (["comma_in_title"], "ok")


def test_op_number_comma_is_not_flagged():
    assert one("Nocturne No. 2 Op. 9 in E Flat Major by Chopin").flags == []
    assert one("Spring Waters Op.14, No.11 by Sergei Rachmaninov").flags == []


def test_two_bys_are_split_into_two_tracks():
    _, tracks = parse_music("Psycho Suite by Bernard Hermann and The Murder by Danny Elfman")
    assert [(t.title, t.artist) for t in tracks] == [
        ("Psycho Suite", "Bernard Hermann"), ("The Murder", "Danny Elfman"),
    ]
    assert all("split_multiple_by" in t.flags and t.status == "ok" for t in tracks)


def test_two_bys_split_at_comma():
    _, tracks = parse_music("Run the World (Girls) by Beyoncé, I Am the Best by 2NE1")
    assert [(t.title, t.artist) for t in tracks] == [
        ("Run the World (Girls)", "Beyoncé"), ("I Am the Best", "2NE1"),
    ]


def test_two_bys_without_any_separator_stay_unparsed():
    t = one("Foo by Bar by Baz")
    assert (t.status, t.title) == ("unparsed", "")


def test_unbalanced_quote_is_cleaned_and_flagged():
    t = one('Oogie Boogie\'s Song" by Danny Elfman')
    assert (t.title, t.artist, t.flags, t.status) == (
        "Oogie Boogie's Song", "Danny Elfman", ["unbalanced_quote"], "ok")


def test_reference_and_empty():
    assert parse_music("")[0] == "empty"
    kind, tracks = parse_music("(same music as CariPrato 2007)")
    assert kind == "reference" and tracks[0].notes == ["same music as CariPrato 2007"]


def test_remix_inside_title_is_not_a_role():
    t = one("Batshit - Ilkay Sencan Remix by Sofi Tukker")
    assert (t.title, t.artist, t.status) == ("Batshit - Ilkay Sencan Remix", "Sofi Tukker", "ok")
