import csv
import json

import pytest

from rg_music import update
from rg_music.update import apply_updates, change_key, diff_page


def row(year, apparatus, music, table="0", idx="0", page="A B", competition="", revid=1):
    return {"gymnast_page": page, "requested_title": page, "revid": revid, "table_index": table, "row_index": idx,
            "year": year, "apparatus": apparatus, "music": music, "competition": competition, "location": "",
            "notes": "", "source_url": "u"}


def test_a_row_inserted_at_the_top_does_not_make_the_others_look_changed():
    old = [row("2025", "Hoop", "Caravan", idx="0"), row("2025", "Ball", "Bolero", idx="1")]
    new = [row("2026", "Hoop", "Carmen", idx="0"), row("2025", "Hoop", "Caravan", idx="1"),
           row("2025", "Ball", "Bolero", idx="2")]
    assert [(c["change"], c["new"]["music"]) for c in diff_page("routine", old, new)] == [("new_music", "Carmen")]


def test_music_where_there_was_none_is_new_in_any_year_and_placeholders_count_as_none():
    old = [row("2026", "Ball", ""), row("2017", "Rope", "??"), row("2016", "Clubs", "Unknown")]
    new = [row("2026", "Ball", "Bolero"), row("2017", "Rope", "Gopak"), row("2016", "Clubs", "?"),
           row("2012", "Hoop", "Caravan")]
    changes = sorted((c["change"], c["new"]["year"], c["old"] and c["old"]["music"]) for c in diff_page("routine", old, new))
    assert changes == [("new_music", "2012", None), ("new_music", "2017", "??"), ("new_music", "2026", "")]


def test_known_music_replaced_or_gone_is_for_review():
    old = [row("2019", "Hoop", "Caravan"), row("2020", "Ball", "Bolero"), row("2021", "Rope", "Gopak")]
    new = [row("2019", "Hoop", "Caravan by Duke Ellington"), row("2021", "Rope", "????")]
    changes = sorted((c["change"], c["old"]["year"]) for c in diff_page("routine", old, new))
    assert changes == [("changed", "2019"), ("removed", "2020"), ("removed", "2021")]


def test_accepted_changes_are_applied_by_content_and_rejected_ones_are_not():
    raw = [row("2019", "Hoop", "Caravan", idx="3"), row("2020", "Ball", "Bolero")]
    edit_old, edit_new = raw[0], row("2019", "Hoop", "Caravan by Duke Ellington", table="u2t0")
    updates = [
        {"kind": "routine", "decision": "accept", "change_key": "k1", "old_row": json.dumps(edit_old),
         "new_row": json.dumps(edit_new)},
        {"kind": "routine", "decision": "reject", "change_key": "k2", "old_row": json.dumps(raw[1]), "new_row": ""},
        {"kind": "routine", "decision": "accept", "change_key": "k3", "old_row": json.dumps(row("1999", "Rope", "x")),
         "new_row": ""},
    ]
    rows, missing = apply_updates(raw, "routine", updates)
    assert [r["music"] for r in rows] == ["Bolero", "Caravan by Duke Ellington"] and missing == ["k3"]


class FakeWiki:
    """Two articles: one edited (an old year changed, a new season added), one unchanged."""
    class Page:
        def __init__(self, title, revid, html):
            self.title, self.revid, self.html, self.url = title, revid, html, "u"

    def __init__(self):
        self.fetched = []

    def revids(self, titles):
        return {"A B": 2, "C D": 1}

    def get_page(self, title, refresh=False):
        self.fetched.append(title)
        return self.Page(title, 2, "<html/>")


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    monkeypatch.setattr(update, "INTERIM", tmp_path)
    monkeypatch.setattr(update, "UPDATES", tmp_path / "wiki_updates.csv")
    old = [row("2024", "Hoop", "Caravan"), row("2025", "Ball", "Bolero"), row("2025", "Ball", "Kalinka", page="C D")]
    with (tmp_path / "routines_raw.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(old[0]))
        w.writeheader()
        w.writerows(old)
    (tmp_path / "extract_report.json").write_text(json.dumps(
        [{"requested_title": p, "page": p, "revid": 1} for p in ("A B", "C D")]), encoding="utf-8")
    fresh = [row("2024", "Hoop", "Caravan by Duke Ellington", revid=2), row("2025", "Ball", "Bolero", revid=2),
             row("2026", "Hoop", "Carmen", revid=2)]
    monkeypatch.setattr(update, "fetch_rows", lambda page, client: {"routine": fresh, "competition": []})
    return tmp_path


def test_run_adds_new_music_and_holds_replaced_music_for_the_owner(workdir):
    wiki = FakeWiki()
    summary = update.run_update(lambda lang: wiki, "2026-01-15")
    assert (summary["pages_changed"], summary["new_music"], summary["changed"], summary["to_review"]) == (1, 1, 1, 1)
    review = list(csv.DictReader((workdir / "update_review.csv").open(encoding="utf-8-sig")))
    assert [(r["change"], r["decision"]) for r in review] == [("changed", ""), ("new_music", "accept")]
    saved = update.load_updates()
    assert [(u["change"], u["decided_by"]) for u in saved] == [("new_music", "rule")]
    assert json.loads(saved[0]["new_row"])["table_index"] == "u2t0"

    # the owner rejects the edit of 2024: it is not shown again, and the data keep the old text
    sheet = workdir / "sheet.csv"
    with sheet.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(review[0]))
        w.writeheader()
        w.writerow({**review[0], "decision": "отклонить", "owner_note": "source error"})
    assert update.import_decisions(sheet, "2026-01-16") == {"reject": 1}
    again = update.run_update(lambda lang: wiki, "2026-01-17")
    assert (again.get("already_reject"), again.get("to_review"), again.get("new_music")) == (1, 0, None)
    # the new-music row is still listed until the owner has seen it; after an import with "accept" it is not
    listed = list(csv.DictReader((workdir / "update_review.csv").open(encoding="utf-8-sig")))
    assert [(r["change"], r["new_music"]) for r in listed] == [("new_music", "Carmen")]
    with sheet.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(listed[0]))
        w.writeheader()
        w.writerows(listed)
    assert update.import_decisions(sheet, "2026-01-18") == {"accept": 1}
    update.run_update(lambda lang: wiki, "2026-01-19")
    assert not list(csv.DictReader((workdir / "update_review.csv").open(encoding="utf-8-sig")))
    rows, _ = apply_updates(list(csv.DictReader((workdir / "routines_raw.csv").open(encoding="utf-8"))), "routine",
                            update.load_updates())
    assert sorted(r["music"] for r in rows if r["gymnast_page"] == "A B") == ["Bolero", "Caravan", "Carmen"]


def test_change_key_ignores_position_and_revision():
    a, b = row("2024", "Hoop", "Caravan", idx="0", revid=1), row("2024", "Hoop", "Caravan", idx="5", revid=9)
    assert change_key("routine", a, None) == change_key("routine", b, None)
