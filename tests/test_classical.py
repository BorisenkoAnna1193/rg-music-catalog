from rg_music.classical import classify, composer_in_title, composer_of, load_composers

C = load_composers()


def test_composer_in_a_credit_is_found_whatever_the_spelling():
    assert composer_of("Aram Khatchaturian", C) == "Aram Khachaturian"
    assert composer_of("Pyotr Ilyich Tchaikovsky, David Garrett", C) == "Pyotr Ilyich Tchaikovsky"
    assert composer_of("Sergei Rachmaninov", C) == "Sergei Rachmaninoff"
    assert composer_of("Michael Jackson", C) == "" and composer_of("", C) == ""


def test_a_first_name_alone_does_not_make_a_composer():
    assert composer_of("Adam Drake", C) == "" and composer_of("Adam Burns", C) == ""
    assert composer_of("Adolphe Charles Adam", C) == "Adolphe Adam" and composer_of("Adolphe Adam", C) == "Adolphe Adam"
    assert composer_of("Maria Tchaikovskaya", C) == ""  # a singer, different surname


def test_an_ensemble_named_after_a_composer_is_a_performer_not_the_composer():
    assert composer_of("Johann Strauss Orchestra", C) == ""
    assert composer_of("Johann Strauss Orchestra, Trio Norte", C) == ""
    assert composer_of("Royal Philharmonic Orchestra, Ludwig van Beethoven", C) == "Ludwig van Beethoven"


def test_composer_at_the_start_of_a_title():
    assert composer_in_title("Mendelssohn: Violin Concerto In E Minor", C) == "Felix Mendelssohn"
    assert composer_in_title("Glinka (la separation) nocturne", C) == "Mikhail Glinka"
    assert composer_in_title("Swan Lake", C) == "" and composer_in_title("Dance of Bach", C) == ""


def test_classify_order_manual_composer_title_default():
    assert classify("boléro", "", ["Maurice Ravel", "Prequell"], ["Boléro"], C, {}) == (1, "composer", "Maurice Ravel")
    assert classify("x", "Carl Orff", [], ["O Fortuna"], C, {}) == (1, "composer", "Carl Orff")
    assert classify("op", "", ["Maksim Mrvica"], ["Etude in D-sharp minor, Op. 8, No. 12"], C, {})[:2] == (1, "title_keyword")
    assert classify("bm", "", ["Queen"], ["Bohemian Rhapsody"], C, {}) == (0, "default", "")       # bare "Rhapsody" is pop too
    assert classify("cb", "", ["Vladimir Cosma"], ["Concerto de Berlin"], C, {}) == (0, "default", "")
    assert classify("boléro", "", ["Maurice Ravel"], ["Boléro"], C, {"boléro": 0}) == (0, "manual", "")  # owner wins
