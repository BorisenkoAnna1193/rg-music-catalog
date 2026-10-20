"""Token and tool statistics of a Claude Code session, for the session-auditor agent.

Reads the session transcripts Claude Code keeps in ~/.claude/projects/<project>/<session>.jsonl (and the
transcripts of its subagents) and prints a Markdown report: tokens by kind, cost in input-token units, the work split
by the owner's prompts, the heaviest tool results and what keeping them in the context cost, repeated commands,
cache rebuilds and long pauses.

    python tools/session_stats.py                 # the latest session of this project
    python tools/session_stats.py --session 93076142
    python tools/session_stats.py --list          # one line per session
    python tools/session_stats.py --json out.json # also write the numbers as JSON

Tokens are exact (from the API usage of every call). A tool result's size is the growth of the context between the
call before it and the call after it, so it is exact for one result per turn and split by characters otherwise.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# Price of each token kind relative to one uncached input token (Anthropic pricing structure: cache reads 0.1x,
# cache writes 1.25x for 5 minutes and 2x for 1 hour, output 5x input for Opus models). Check if the pricing changes.
WEIGHTS = {"input": 1.0, "cache_write_5m": 1.25, "cache_write_1h": 2.0, "cache_read": 0.1, "output": 5.0}

PAUSE_MIN = 5          # a gap between two calls longer than this (minutes) is reported
REBUILD_TOKENS = 20000  # a cache write this big after the first call = the cached context was rebuilt
TOP = 15


def project_dir(cwd: Path) -> Path:
    return Path.home() / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(cwd.resolve()))


@dataclass
class Call:
    """One API call (one assistant message)."""
    ts: datetime
    agent: str
    input: int
    cache_read: int
    cache_write_5m: int
    cache_write_1h: int
    output: int
    tools: list[tuple[str, str, str]] = field(default_factory=list)  # (tool_use_id, name, short input)

    @property
    def context(self) -> int:
        return self.input + self.cache_read + self.cache_write_5m + self.cache_write_1h

    @property
    def units(self) -> float:
        return (self.input * WEIGHTS["input"] + self.cache_read * WEIGHTS["cache_read"]
                + self.cache_write_5m * WEIGHTS["cache_write_5m"] + self.cache_write_1h * WEIGHTS["cache_write_1h"]
                + self.output * WEIGHTS["output"])


@dataclass
class Result:
    tool_id: str
    name: str
    what: str
    chars: int
    call_index: int  # index of the first call that sees this result
    tokens: int = 0
    carried: int = 0  # later calls that re-read it from the cache


def short_input(name: str, inp: dict) -> str:
    """The input that identifies the call, whole (the report shortens it); scratchpad paths become $SCRATCH."""
    key = next((k for k in ("command", "file_path", "pattern", "query", "url") if k in inp), None)
    text = str(inp[key]) if key else json.dumps(inp, ensure_ascii=False)
    text = re.sub(r"/(private/)?tmp/claude-\d+/[^/\s]+/[0-9a-f-]{36}(/scratchpad)?", "$SCRATCH", text)
    return re.sub(r"\s+", " ", text)


def result_chars(content) -> int:
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        return sum(len(c.get("text", "")) if c.get("type") == "text" else 1500 for c in content)  # image ~1.5k
    return 0


def prompt_text(content) -> str | None:
    """The owner's words, or None for tool results and harness messages."""
    if isinstance(content, list):
        if any(c.get("type") == "tool_result" for c in content):
            return None
        content = " ".join(c.get("text", "") for c in content if c.get("type") == "text")
    text = re.sub(r"<(system-reminder|ide_selection|ide_opened_file)>.*?</\1>", "", content or "", flags=re.S).strip()
    if not text or text.startswith("<") or text.startswith("Caveat:"):
        return None
    return re.sub(r"\s+", " ", text)[:80]


def read_transcript(path: Path, agent: str):
    calls: dict[str, Call] = {}
    results: list[tuple[datetime, str, int]] = []   # (ts, tool_use_id, chars)
    prompts: list[tuple[datetime, str]] = []
    for line in path.open(encoding="utf-8"):
        d = json.loads(line)
        if d.get("type") not in ("assistant", "user") or "timestamp" not in d:
            continue
        ts = datetime.fromisoformat(d["timestamp"].replace("Z", "+00:00"))
        msg = d["message"]
        if d["type"] == "assistant":
            u = msg.get("usage") or {}
            cw = u.get("cache_creation") or {}
            c = calls.get(msg["id"])
            if c is None:  # one message is logged once per content block, with the same usage
                w1h = cw.get("ephemeral_1h_input_tokens", 0)
                c = calls[msg["id"]] = Call(ts, agent, u.get("input_tokens", 0), u.get("cache_read_input_tokens", 0),
                                            u.get("cache_creation_input_tokens", 0) - w1h, w1h,
                                            u.get("output_tokens", 0))
            for block in msg.get("content", []):
                if block.get("type") == "tool_use":
                    c.tools.append((block["id"], block["name"], short_input(block["name"], block.get("input", {}))))
        else:
            content = msg.get("content")
            if isinstance(content, list):
                for block in content:
                    if block.get("type") == "tool_result":
                        results.append((ts, block["tool_use_id"], result_chars(block.get("content"))))
            if not d.get("isMeta") and not d.get("isSidechain"):
                text = prompt_text(content)
                if text:
                    prompts.append((ts, text))
    return sorted(calls.values(), key=lambda c: c.ts), results, prompts


def analyse(main: Path) -> dict:
    calls, raw_results, prompts = read_transcript(main, "main")
    sub_calls = []
    sub_dir = main.with_suffix("") / "subagents"
    for sub in sorted(sub_dir.glob("*.jsonl")) if sub_dir.is_dir() else []:
        meta = sub.with_suffix(".meta.json")
        name = json.loads(meta.read_text()).get("agentType", sub.stem) if meta.exists() else sub.stem
        sub_calls += read_transcript(sub, name)[0]

    # tool results of the main thread: size = context growth before the next call
    tool_info = {tid: (name, what) for c in calls for tid, name, what in c.tools}
    results: list[Result] = []
    times = [c.ts for c in calls]
    for ts, tid, chars in raw_results:
        nxt = next((i for i, t in enumerate(times) if t >= ts), None)
        if nxt is None or tid not in tool_info:
            continue
        results.append(Result(tid, *tool_info[tid], chars, nxt))
    by_call = defaultdict(list)
    for r in results:
        by_call[r.call_index].append(r)
    resets = [i for i in range(1, len(calls)) if calls[i].context < calls[i - 1].context * 0.6]
    for i, rs in by_call.items():
        growth = max(calls[i].context - calls[i - 1].context, 0) if i else 0
        total = sum(r.chars for r in rs) or 1
        next_reset = next((j for j in resets if j > i), len(calls))
        for r in rs:
            r.tokens = round(growth * r.chars / total)
            r.carried = next_reset - i - 1

    def totals(cs):
        t = Counter()
        for c in cs:
            t["calls"] += 1
            t["input"] += c.input
            t["cache_read"] += c.cache_read
            t["cache_write_5m"] += c.cache_write_5m
            t["cache_write_1h"] += c.cache_write_1h
            t["output"] += c.output
            t["units"] += c.units
        return t

    # the owner's prompts split the main thread into tasks
    tasks = []
    for k, (ts, text) in enumerate(prompts):
        end = prompts[k + 1][0] if k + 1 < len(prompts) else datetime.max.replace(tzinfo=ts.tzinfo)
        cs = [c for c in calls if ts <= c.ts < end]
        if cs:
            subs = [c for c in sub_calls if ts <= c.ts < end]
            tasks.append({"prompt": text, "start": ts, "minutes": (cs[-1].ts - ts).total_seconds() / 60,
                          "tools": sum(len(c.tools) for c in cs), **totals(cs + subs),
                          "subagent_units": totals(subs)["units"]})

    tool_counts = Counter(name for c in calls for _, name, _ in c.tools)
    tool_tokens = Counter()
    for r in results:
        tool_tokens[r.name] += r.tokens
    repeated = Counter((name, what) for c in calls for _, name, what in c.tools if name in ("Bash", "Read", "Grep"))
    pauses = [(calls[i - 1].ts, (calls[i].ts - calls[i - 1].ts).total_seconds() / 60)
              for i in range(1, len(calls)) if (calls[i].ts - calls[i - 1].ts).total_seconds() > PAUSE_MIN * 60]
    rebuilds = [(calls[i].ts, calls[i].cache_write_5m + calls[i].cache_write_1h) for i in range(1, len(calls))
                if calls[i].cache_write_5m + calls[i].cache_write_1h > REBUILD_TOKENS]
    sub_by_agent = defaultdict(list)
    for c in sub_calls:
        sub_by_agent[c.agent].append(c)

    return {
        "session": main.stem, "start": calls[0].ts if calls else None, "end": calls[-1].ts if calls else None,
        "main": totals(calls), "subagents": {a: totals(cs) for a, cs in sub_by_agent.items()},
        "peak_context": max((c.context for c in calls), default=0), "context_resets": len(resets),
        "tasks": tasks, "tool_counts": tool_counts, "tool_tokens": tool_tokens,
        "heaviest": sorted(results, key=lambda r: -r.tokens * (1 + r.carried * WEIGHTS["cache_read"]))[:TOP],
        "repeated": [(k, n) for k, n in repeated.most_common() if n > 1][:TOP],
        "pauses": pauses, "rebuilds": rebuilds,
    }


def cut(text: str, n: int = 90) -> str:
    return (text[:n] + "…" if len(text) > n else text).replace("|", "/")


def fmt(n: float) -> str:
    return f"{n / 1000:,.1f}k" if n >= 1000 else f"{n:,.0f}"


def report(a: dict) -> str:
    m = a["main"]
    out = [f"# Session {a['session']}",
           f"{a['start']:%Y-%m-%d %H:%M} – {a['end']:%H:%M} UTC · {m['calls']} API calls · peak context "
           f"{fmt(a['peak_context'])} · context resets (compaction / clear): {a['context_resets']}", "",
           "## Tokens", "| | main |" + "".join(f" {s} |" for s in a["subagents"]),
           "|---|---|" + "---|" * len(a["subagents"])]
    for key in ("calls", "input", "cache_read", "cache_write_5m", "cache_write_1h", "output", "units"):
        out.append(f"| {key} | {fmt(m[key])} |" + "".join(f" {fmt(s[key])} |" for s in a["subagents"].values()))
    out += ["", "`units` = cost in uncached-input-token equivalents (weights: "
            + ", ".join(f"{k} {v}" for k, v in WEIGHTS.items()) + ").", "",
            "## Tasks (split by the owner's prompts)", "| start | prompt | min | tools | calls | output | units | of it subagents |",
            "|---|---|---|---|---|---|---|---|"]
    for t in a["tasks"]:
        out.append(f"| {t['start']:%H:%M} | {cut(t['prompt'])} | {t['minutes']:.0f} | {t['tools']} | "
                   f"{t['calls']} | {fmt(t['output'])} | {fmt(t['units'])} | {fmt(t['subagent_units'])} |")
    out += ["", "## Tools", "| tool | calls | tokens added to context |", "|---|---|---|"]
    for name, n in a["tool_counts"].most_common():
        out.append(f"| {name} | {n} | {fmt(a['tool_tokens'][name])} |")
    out += ["", "## Heaviest tool results",
            "`carried` = later calls that re-read the result from the cache; `carry units` = tokens × carried × "
            f"{WEIGHTS['cache_read']} (what keeping it in the context cost on top of reading it once).",
            "| tool | input | tokens | carried | carry units |", "|---|---|---|---|---|"]
    for r in a["heaviest"]:
        out.append(f"| {r.name} | `{cut(r.what)}` | {fmt(r.tokens)} | {r.carried} | "
                   f"{fmt(r.tokens * r.carried * WEIGHTS['cache_read'])} |")
    out += ["", "## Repeated commands and reads"]
    out += [f"- {n}× {name}: `{what}`" for (name, what), n in [((k[0], cut(k[1], 140)), n) for k, n in a["repeated"]]] or ["- none"]
    out += ["", f"## Pauses over {PAUSE_MIN} min (owner thinking, or Claude waiting on a long command)"]
    out += [f"- {ts:%H:%M}: {mins:.0f} min" for ts, mins in a["pauses"]] or ["- none"]
    out += ["", f"## Cache rebuilds (cache write > {fmt(REBUILD_TOKENS)} after the first call)"]
    out += [f"- {ts:%H:%M}: {fmt(n)} written" for ts, n in a["rebuilds"]] or ["- none"]
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--session", help="session id or its prefix (default: the latest)")
    ap.add_argument("--project", type=Path, default=Path.cwd(), help="project directory (default: cwd)")
    ap.add_argument("--list", action="store_true", help="one line per session")
    ap.add_argument("--json", type=Path, help="also write the numbers as JSON")
    args = ap.parse_args()

    sessions = sorted(project_dir(args.project).glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    if args.list:
        print("| session | start | calls | output | units | subagent units |\n|---|---|---|---|---|---|")
        for p in sessions:
            a = analyse(p)
            if a["start"]:
                sub = sum(s["units"] for s in a["subagents"].values())
                print(f"| {p.stem[:8]} | {a['start']:%Y-%m-%d %H:%M} | {a['main']['calls']} | "
                      f"{fmt(a['main']['output'])} | {fmt(a['main']['units'])} | {fmt(sub)} |")
        return
    picked = [p for p in sessions if p.stem.startswith(args.session)] if args.session else sessions[-1:]
    if not picked:
        raise SystemExit(f"no session {args.session!r} in {project_dir(args.project)}")
    a = analyse(picked[-1])
    print(report(a))
    if args.json:
        a["heaviest"] = [r.__dict__ for r in a["heaviest"]]
        args.json.write_text(json.dumps(a, default=str, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
