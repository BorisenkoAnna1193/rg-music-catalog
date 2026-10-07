import csv

from rg_music.music_parser import Track, parse_music
from rg_music.parse import apply_overrides, load_overrides

CELL = "Illumination by Jennifer Thomas, Earth and Fire by Udi Harpaz & Ron Klein"


def write(path, rows):
    fields = ["raw_text", "track_no", "title", "work", "artist", "performer", "notes", "reason"]
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows({**{k: "" for k in fields}, **r} for r in rows)


def test_overrides_are_read_in_track_order_and_marked_manual(tmp_path):
    path = tmp_path / "o.csv"
    write(path, [{"raw_text": CELL, "track_no": "2", "title": "Earth and Fire", "artist": "Udi Harpaz & Ron Klein"},
                 {"raw_text": CELL, "track_no": "1", "title": "Illumination", "artist": "Jennifer Thomas"}])
    tracks = load_overrides(path)[CELL]
    assert [t.title for t in tracks] == ["Illumination", "Earth and Fire"]
    assert all(t.status == "manual" for t in tracks)


def test_override_replaces_the_unparsed_cell_and_leaves_other_tracks_alone(tmp_path):
    path = tmp_path / "o.csv"
    write(path, [{"raw_text": CELL, "track_no": "1", "title": "Illumination", "artist": "Jennifer Thomas"},
                 {"raw_text": CELL, "track_no": "2", "title": "Earth and Fire", "artist": "Udi Harpaz & Ron Klein"}])
    _, tracks = parse_music(f'"Fine" by Someone; {CELL}')
    assert [t.status for t in tracks] == ["ok", "unparsed"]
    result = apply_overrides(tracks, load_overrides(path))
    assert [(t.title, t.status) for t in result] == [("Fine", "ok"), ("Illumination", "manual"), ("Earth and Fire", "manual")]


def test_missing_overrides_file_means_no_overrides(tmp_path):
    assert load_overrides(tmp_path / "nope.csv") == {}
    t = Track(raw_text="x", title="x")
    assert apply_overrides([t], {}) == [t]


def test_the_real_overrides_file_covers_every_cell_the_rules_leave_unparsed():
    overrides = load_overrides()
    assert len(overrides) == 9  # 6 ambiguous cells, a "(same music as ...)" reference, a slash credit, a performer found by ear
    assert all(all(t.title and t.status == "manual" for t in tracks) for tracks in overrides.values())
