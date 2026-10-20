import importlib.util
import json
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location("session_stats", Path(__file__).parent.parent / "tools" / "session_stats.py")
session_stats = importlib.util.module_from_spec(spec)
sys.modules["session_stats"] = session_stats  # dataclasses look the module up
spec.loader.exec_module(session_stats)


def usage(read, write, out):
    return {"input_tokens": 2, "cache_read_input_tokens": read, "cache_creation_input_tokens": write,
            "cache_creation": {"ephemeral_1h_input_tokens": write}, "output_tokens": out}


def assistant(ts, mid, u, blocks):
    return {"type": "assistant", "timestamp": ts, "message": {"id": mid, "usage": u, "content": blocks}}


def user(ts, content):
    return {"type": "user", "timestamp": ts, "message": {"content": content}}


def test_analyse_counts_each_message_once_and_sizes_results(tmp_path):
    tool = {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "cat big.csv"}}
    lines = [
        user("2026-10-20T10:00:00Z", "<system-reminder>x</system-reminder>Посчитай что-нибудь"),
        # one message logged twice (thinking, then tool_use) with the same usage
        assistant("2026-10-20T10:00:05Z", "m1", usage(0, 10000, 100), [{"type": "thinking"}]),
        assistant("2026-10-20T10:00:05Z", "m1", usage(0, 10000, 100), [tool]),
        user("2026-10-20T10:00:06Z", [{"type": "tool_result", "tool_use_id": "t1", "content": "a" * 4000}]),
        assistant("2026-10-20T10:00:10Z", "m2", usage(10000, 1000, 50), [{"type": "text", "text": "ok"}]),
        assistant("2026-10-20T10:00:20Z", "m3", usage(11000, 0, 50), [{"type": "text", "text": "done"}]),
    ]
    path = tmp_path / "s.jsonl"
    path.write_text("\n".join(json.dumps(x) for x in lines), encoding="utf-8")

    a = session_stats.analyse(path)

    assert a["main"]["calls"] == 3
    assert a["main"]["output"] == 200
    assert [t["prompt"] for t in a["tasks"]] == ["Посчитай что-нибудь"]
    (r,) = a["heaviest"]
    assert (r.name, r.tokens, r.carried) == ("Bash", 1000, 1)
    assert "cat big.csv" in session_stats.report(a)
