import csv
import json

import pytest

from rg_music import llm_parse
from rg_music.llm_parse import (
    SCHEMA, CellOut, OpenRouter, TrackOut, is_verbatim, load_env_key, main, merge_resolved, resolve_cells,
)

CELL = "Illumination by Jennifer Thomas, Earth and Fire by Udi Harpaz & Ron Klein"
GOOD = {"tracks": [
    {"title": "Illumination", "work": "", "artist": "Jennifer Thomas", "performer": "", "notes": ""},
    {"title": "Earth and Fire", "work": "", "artist": "Udi Harpaz & Ron Klein", "performer": "", "notes": ""},
]}


class FakeResponse:
    def __init__(self, payload=None, status=200):
        self.status_code, self._payload = status, payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    def json(self):
        return {"choices": [{"message": {"content": json.dumps(self._payload)}}]}


class FakePost:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), 0

    def __call__(self, url, **kwargs):
        self.calls += 1
        return self.responses.pop(0)


def client(*responses):
    post = FakePost(*responses)
    return OpenRouter("key", "test/model", post), post


def test_schema_matches_the_pydantic_model_and_is_strict():
    item = SCHEMA["properties"]["tracks"]["items"]
    assert set(item["properties"]) == set(item["required"]) == set(TrackOut.model_fields)
    assert item["additionalProperties"] is False and SCHEMA["additionalProperties"] is False
    body = OpenRouter("k", "m").request_body(CELL)
    assert body["response_format"]["json_schema"]["strict"] is True and body["temperature"] == 0
    assert body["messages"][1] == {"role": "user", "content": CELL}


def test_verbatim_check_rejects_invented_words_and_empty_titles():
    ok = TrackOut(**GOOD["tracks"][1])
    assert is_verbatim(ok, CELL)
    invented = ok.model_copy(update={"artist": "Hans Zimmer"})
    assert not is_verbatim(invented, CELL)
    assert not is_verbatim(ok.model_copy(update={"title": ""}), CELL)


def test_answer_is_cached_so_a_second_run_makes_no_request():
    c, post = client(FakeResponse(GOOD))
    cache = {}
    first = resolve_cells([CELL], c, cache)
    second = resolve_cells([CELL], c, cache)
    assert post.calls == 1 and not first[CELL]["from_cache"] and second[CELL]["from_cache"]
    assert [t.title for t in second[CELL]["tracks"]] == ["Illumination", "Earth and Fire"]


def test_answer_outside_the_schema_is_rejected_and_not_cached():
    c, _ = client(FakeResponse({"tracks": [{"title": "x"}]}))
    cache = {}
    with pytest.raises(RuntimeError, match="schema"):
        resolve_cells([CELL], c, cache)
    assert cache == {}
    with pytest.raises(Exception):
        CellOut.model_validate({"tracks": []})  # at least one track


def test_server_errors_are_retried(monkeypatch):
    monkeypatch.setattr(llm_parse.time, "sleep", lambda s: None)
    c, post = client(FakeResponse(status=503), FakeResponse(status=429), FakeResponse(GOOD))
    assert c.parse_cell(CELL) == GOOD and post.calls == 3


def _row(rid, no, raw, status, title=""):
    return {"routine_id": rid, "track_no": str(no), "title": title, "work": "", "artist": "", "performer": "",
            "notes": "", "flags": "multiple_by" if status == "unparsed" else "", "status": status, "raw_text": raw}


def test_model_tracks_replace_the_unparsed_row_and_tracks_are_renumbered():
    rows = [_row("r1", 1, "Fine by Someone", "ok", "Fine"), _row("r1", 2, CELL, "unparsed"), _row("r2", 1, "Other", "ok", "Other")]
    answers = {CELL: {"tracks": CellOut.model_validate(GOOD).tracks}}
    resolved, llm_rows = merge_resolved(rows, answers, "test/model")
    assert [(r["routine_id"], r["track_no"], r["title"], r["status"]) for r in resolved] == [
        ("r1", 1, "Fine", "ok"), ("r1", 2, "Illumination", "llm"), ("r1", 3, "Earth and Fire", "llm"), ("r2", 1, "Other", "ok")]
    assert resolved[1]["flags"] == "llm_parsed" and len(llm_rows) == 2 and all(r["verbatim_ok"] for r in llm_rows)


def test_invented_track_is_marked_unverified():
    bad = {"tracks": [{"title": "Illumination", "work": "", "artist": "Somebody Else", "performer": "", "notes": ""}]}
    resolved, llm_rows = merge_resolved([_row("r1", 1, CELL, "unparsed")], {CELL: {"tracks": CellOut.model_validate(bad).tracks}}, "m")
    assert resolved[0]["status"] == "llm_unverified" and "llm_unverified" in resolved[0]["flags"]
    assert llm_rows[0]["verbatim_ok"] is False


def test_main_without_a_key_stops_before_any_request(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with (tmp_path / "tracks.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(_row("r", 1, "x", "ok")))
        w.writeheader()
        w.writerow(_row("r1", 1, CELL, "unparsed"))
    assert main(["--dir", str(tmp_path)]) == 2
    assert "OPENROUTER_API_KEY" in capsys.readouterr().err
    assert main(["--dir", str(tmp_path), "--dry-run"]) == 0


def test_key_comes_from_the_environment_first_then_from_the_env_file(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text('# comment\nOTHER=1\nOPENROUTER_API_KEY="sk-from-file"\n', encoding="utf-8")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert load_env_key(env_file) == "sk-from-file"
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-from-env")
    assert load_env_key(env_file) == "sk-from-env"
    monkeypatch.delenv("OPENROUTER_API_KEY")
    assert load_env_key(tmp_path / "missing.env") == ""
