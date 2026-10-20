"""Run the pipeline from a given stage, time every stage, and compare the result with the last commit.

Stages in order: native_extract, merge, parse, works, resolve, [mb_works, resolve_mb], db, site_export, tests.
MusicBrainz (network, slow) runs only with --mb, once, after the first resolve: the joins it finds are cached in
work_mb_links.csv, so later runs without --mb still apply them.

The comparison with HEAD (git show HEAD:<file>) is what used to be done by hand after a rerun, too late:
  * counts: routines, works, versions, gymnasts with music;
  * titles whose split decision changed (work_splits.csv), with LOST_OWNER_DECISION when a title the owner had joined
    is no longer joined by the owner;
  * suspicious joins: a NEW track put into a work that already existed while its credit shares no name with any
    credit of that work ("Rondo" by Dupéré into Schnittke's "Rondo").
Written to data/interim/pipeline_report.json; the exit code is 1 when tests fail or an owner decision was lost.

Usage:
    python -m rg_music.pipeline                    # from merge to site_export, then tests
    python -m rg_music.pipeline --from works --mb  # rematch works, with MusicBrainz
    python -m rg_music.pipeline --check            # only the comparison with HEAD
    python -m rg_music.pipeline --check --base HEAD~2
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

from rg_music.works import name_tokens

INTERIM = Path("data/interim")
STAGES = [
    ("native_extract", ["-m", "rg_music.native_extract"]),
    ("merge", ["-m", "rg_music.merge"]),
    ("parse", ["-m", "rg_music.parse"]),
    ("works", ["-m", "rg_music.works"]),
    ("resolve", ["-m", "rg_music.works", "--resolve"]),
    ("mb_works", ["-m", "rg_music.mb_works"]),
    ("resolve_mb", ["-m", "rg_music.works", "--resolve"]),
    ("db", ["-m", "rg_music.db"]),
    ("site_export", ["-m", "rg_music.site_export"]),
    ("tests", ["-m", "pytest", "-q"]),
]
MB_STAGES = {"mb_works", "resolve_mb"}


def _rows(text: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(text.lstrip("﻿"))))


def _head(path: Path, base: str = "HEAD") -> list[dict]:
    out = subprocess.run(["git", "show", f"{base}:{path.as_posix()}"], capture_output=True, text=True)
    return _rows(out.stdout) if out.returncode == 0 else []


def _now(path: Path) -> list[dict]:
    return _rows(path.read_text(encoding="utf-8-sig")) if path.exists() else []


def counts(routines: list[dict], works: list[dict], versions: list[dict]) -> dict:
    return {"routines": len(routines), "works": len(works), "versions": len(versions),
            "gymnasts_with_music": len({r["gymnast_page"] for r in routines if r.get("music")})}


def split_changes(old: list[dict], new: list[dict]) -> list[dict]:
    before = {r["title_key"]: r["decision"] for r in old}
    after = {r["title_key"]: r["decision"] for r in new}
    out = []
    for key in sorted(set(before) | set(after)):
        if before.get(key) != after.get(key):
            lost = before.get(key) == "joined_by_owner" and after.get(key) != "joined_by_owner"
            out.append({"title": key, "before": before.get(key, ""), "after": after.get(key, ""),
                        "flag": "LOST_OWNER_DECISION" if lost else ""})
    return out


def suspicious_joins(old: list[dict], new: list[dict]) -> list[dict]:
    """New tracks in a work that existed before, with a credit sharing no name with that work's earlier credits."""
    seen = {(t["routine_id"], t["track_no"]) for t in old}
    credits: dict[str, set[str]] = defaultdict(set)
    for t in old:
        credits[t["work_key"]] |= name_tokens(t["artist"])
    out = []
    for t in new:
        names = name_tokens(t["artist"])
        if (t["routine_id"], t["track_no"]) in seen or t["work_key"] not in credits or not names:
            continue
        if credits[t["work_key"]] and not names & credits[t["work_key"]]:
            out.append({"work_key": t["work_key"], "title": t["title"], "artist": t["artist"], "routine_id": t["routine_id"]})
    return out


def unused_owner_rows(path: Path = INTERIM / "merge_report.json") -> list[str]:
    """Owner's rows in data/manual/ that matched nothing in the last merge (the source text changed?)."""
    return json.loads(path.read_text(encoding="utf-8")).get("unused_owner_rows", []) if path.exists() else []


def compare_with_head(base: str = "HEAD") -> dict:
    files = {name: INTERIM / f"{name}.csv" for name in ("routines_merged", "works", "versions", "work_splits", "track_works")}
    old = {k: _head(p, base) for k, p in files.items()}
    new = {k: _now(p) for k, p in files.items()}
    return {
        "counts_head": counts(old["routines_merged"], old["works"], old["versions"]),
        "counts_now": counts(new["routines_merged"], new["works"], new["versions"]),
        "split_changes": split_changes(old["work_splits"], new["work_splits"]),
        "suspicious_joins": suspicious_joins(old["track_works"], new["track_works"]),
        "unused_owner_rows": unused_owner_rows(),
    }


def print_report(report: dict) -> None:
    head, now = report["counts_head"], report["counts_now"]
    print(f"\ncompared with {report.get('base', 'HEAD')}: " + ", ".join(f"{k} {head[k]} -> {now[k]}" for k in now))
    for c in report["split_changes"]:
        print(f"  split decision  {c['title']}: {c['before'] or '-'} -> {c['after'] or '-'} {c['flag']}")
    for j in report["suspicious_joins"]:
        print(f"  check join      {j['title']} by {j['artist']} -> work '{j['work_key']}' ({j['routine_id']})")
    for row in report.get("unused_owner_rows", []):
        print(f"  unused owner row  {row}")
    if "timings" in report:
        print("timings: " + ", ".join(f"{k} {v:.0f}s" for k, v in report["timings"].items()))


def main(argv: list[str] | None = None) -> int:
    names = [n for n, _ in STAGES]
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--from", dest="start", choices=names, default="merge")
    ap.add_argument("--to", dest="stop", choices=names, default="tests")
    ap.add_argument("--mb", action="store_true", help="also ask MusicBrainz (network) for the split groups")
    ap.add_argument("--check", action="store_true", help="only compare the current files with HEAD")
    ap.add_argument("--base", default="HEAD", help="the commit to compare with (default HEAD)")
    args = ap.parse_args(argv)

    timings: dict[str, float] = {}
    failed = ""
    if not args.check:
        todo = names[names.index(args.start): names.index(args.stop) + 1]
        for name, cmd in STAGES:
            if name not in todo or (name in MB_STAGES and not args.mb):
                continue
            t0 = time.monotonic()
            print(f"== {name}", flush=True)
            result = subprocess.run([sys.executable, *cmd], capture_output=True, text=True)
            timings[name] = time.monotonic() - t0
            lines = (result.stdout + result.stderr).strip().splitlines()
            print("\n".join(lines[-3:]))
            if result.returncode != 0:
                failed = name
                break
    report = {**compare_with_head(args.base), "timings": timings, "failed_stage": failed, "base": args.base}
    (INTERIM / "pipeline_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print_report(report)
    lost = any(c["flag"] for c in report["split_changes"])
    if failed:
        print(f"FAILED at {failed}")
    return 1 if failed or lost else 0


if __name__ == "__main__":
    sys.exit(main())
