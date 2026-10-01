"""Rule-based parser for the free-text "music" cell.

One cell -> list of Track. Rules first; anything the rules cannot resolve is
flagged so that a later LLM pass (or a human) can take it.

Credits:
    artist     everyone credited with "by" / "composed by" / "original by", composer
               first: "Georgy Sviridov, Alexander Vedernikov & Russian Philharmonic"
    performer  explicit "performed by" / "conducted by"
Composer and performer are not told apart in the source; that is left to entity
resolution. The "excerpt" level of the music model is not parsed: rules cannot
tell an excerpt from a title, and an unstated excerpt must stay unknown.

Several works in one cell become several tracks (same routine_id):
    "A by X and B by Y"        -> A by X, B by Y         (flag split_multiple_by)
    "A / B / C by X / Y / Z"   -> A by X, B by Y, C by Z (flag slash_split)
    '"Poeta (remix)", original by A, remix by B' -> title "Poeta (remix by B)", artist A

Status of a track:
    ok        title and a credit
    partial   title found but a REVIEW flag is set (no credit, unpaired slashes)
    unparsed  rules gave up; raw_text is kept
Other flags (comma_in_title, credit_without_by, unbalanced_quote, remix, ...) are
informational: the heuristic was applied, the flag shows where.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace

MULTIPLE_BY = "multiple_by"  # two "by" the rules could not separate -> unparsed
REVIEW_FLAGS = {"no_credit", "slash_in_credit"}

_MARKER = re.compile(
    # "original by" / "remix by" only after a comma or "(": mid-title "Remix by X" is not a role
    r"(?:,\s*|\(\s*)(?P<r1>as\s+composed|composed|performed|conducted|original|remix)\s+by\s+"
    r"|(?:,\s*|\(\s*|\s+)(?:(?P<r2>as\s+composed|composed|performed|conducted)\s+)?by\s+",
    re.I,
)
_WORK_TAIL = re.compile(
    r"(?:\s+|,\s*)music\s+from\s+(?P<a>.+)$"
    r"|\(\s*from\s+(?P<b>.+?)\s*\)\s*$"
    r"|,\s*from\s+(?P<c>.+)$",
    re.I,
)
_OST = re.compile(r"\(?\s*(?P<w>[^()]+?)\s*(?:\(?\s*(?:OST|Original Television Soundtrack)\s*\)?)\s*\)?$", re.I)
_REFERENCE = re.compile(r"^\(?\s*same music as", re.I)
_SLASH = r"\s/\s?|\s?/\s"
_BETWEEN_BYS = re.compile(r",\s+|\s+and\s+|\s+&\s+")
_ROLE = {
    "as composed": "composer", "composed": "composer",
    "performed": "performer", "conducted": "performer",
    "original": "artist", "remix": "remix",
}


@dataclass
class Track:
    raw_text: str
    title: str = ""
    work: str = ""
    artist: str = ""
    performer: str = ""
    notes: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        if MULTIPLE_BY in self.flags or not self.title:
            return "unparsed"
        return "partial" if REVIEW_FLAGS & set(self.flags) else "ok"


def _mask_quotes(text: str) -> str:
    """Replace everything inside "..." with '_' so separators there are ignored."""
    return re.sub(r'"[^"]*"', lambda m: "_" * len(m.group()), text)


def _split_masked(text: str, pattern: str) -> list[str]:
    masked, parts, start = _mask_quotes(text), [], 0
    for m in re.finditer(pattern, masked):
        parts.append(text[start:m.start()])
        start = m.end()
    parts.append(text[start:])
    return [p.strip() for p in parts if p.strip()]


def _clean_value(value: str) -> tuple[str, list[str], str]:
    """Strip punctuation, pull out a trailing "(note)" and ", from X" -> (value, notes, work)."""
    value, notes, work = value.strip(" ,;."), [], ""
    m = re.search(r"\s*\(([^()]*)\)$", value)
    if m:
        notes.append(m.group(1).strip())
        value = value[:m.start()].strip(" ,;.")
    elif value.endswith(")") and value.count(")") > value.count("("):
        value = value[:-1].strip(" ,;.")
    m = re.search(r",\s*(?:music\s+)?from\s+(.+)$", value, re.I)
    if m:
        work = m.group(1).strip()
        value = value[:m.start()].strip(" ,;.")
    return value, notes, work


def _interpret_remainder(rem: str, track: Track) -> None:
    """Text left after the quoted titles: "(from X)", "from X", "(X OST)", "(musical)", ", Artist"."""
    rem = rem.strip(" ,")
    if not rem:
        return
    m = _WORK_TAIL.search(" " + rem) or re.match(r"^from\s+(?P<c>.+)$", rem, re.I)
    if m:
        track.work = next(g for g in m.groups() if g).strip(" \"")
    elif re.search(r"\b(?:OST|soundtrack)\b", rem, re.I) and (o := _OST.match(rem)):
        track.work = o.group("w").strip(" (\"")
    elif rem.startswith("("):
        track.notes.append(rem.strip("() "))
    else:
        track.artist = rem
        track.flags.append("credit_without_by")


def _with_remix(title: str, remix_by: str) -> str:
    if re.search(r"\(\s*remix\s*\)$", title, re.I):
        return re.sub(r"\(\s*remix\s*\)$", f"(remix by {remix_by})", title, flags=re.I)
    return f"{title} (remix by {remix_by})"


def _split_between_bys(text: str, plain: list[re.Match]) -> list[str] | None:
    """Cut "A by X, B by Y" into ["A by X", "B by Y"] at the last separator between two "by"."""
    masked, pieces, start = _mask_quotes(text), [], 0
    for cur, nxt in zip(plain, plain[1:]):
        seps = list(_BETWEEN_BYS.finditer(masked, cur.end(), nxt.start()))
        if not seps:
            return None
        pieces.append(text[start:seps[-1].start()])
        start = seps[-1].end()
    pieces.append(text[start:])
    return pieces


def _parse_unit(text: str, extra_flags: tuple[str, ...] = ()) -> list[Track]:
    """Parse one unit (no ';' or ' | ' inside) into one or more tracks."""
    raw = text
    flags = list(extra_flags)
    if text.count('"') % 2:
        text = text.replace('"', "")
        flags.append("unbalanced_quote")
    text = text.strip()

    masked = _mask_quotes(text)
    markers = list(_MARKER.finditer(masked))
    plain = [m for m in markers if not (m.group("r1") or m.group("r2"))]

    if len(plain) >= 2:
        if re.search(_SLASH, masked):  # "A by X / B by Y": one unit per slash-separated part
            return [t for part in _split_masked(text, _SLASH) for t in _parse_unit(part, tuple(flags))]
        pieces = _split_between_bys(text, plain)
        if pieces is None:
            return [Track(raw_text=raw, flags=flags + [MULTIPLE_BY])]
        return [t for p in pieces for t in _parse_unit(p, (*flags, "split_multiple_by"))]

    title_part = (text[:markers[0].start()] if markers else text).strip(" ,")
    track = Track(raw_text=raw, flags=flags)

    # titles (+ shared work) ---------------------------------------------------
    if title_part.startswith('"'):
        titles = [t.strip() for t in re.findall(r'"([^"]*)"', title_part)]
        _interpret_remainder(re.sub(r'"[^"]*"', "", title_part), track)
    else:
        if m := _WORK_TAIL.search(title_part):
            track.work = next(g for g in m.groups() if g).strip(' "')
            title_part = title_part[:m.start()].strip(" ,")
        titles = _split_masked(title_part, _SLASH)
        if any(re.search(r",(?!\s*(?:Op|No)\b)", t) for t in titles):
            track.flags.append("comma_in_title")

    # credits ------------------------------------------------------------------
    composers: list[str] = []
    artists = [track.artist] if track.artist else []
    performers: list[str] = []
    remix_by = ""
    for i, m in enumerate(markers):
        end = markers[i + 1].start() if i + 1 < len(markers) else len(text)
        role = _ROLE.get(re.sub(r"\s+", " ", (m.group("r1") or m.group("r2") or "").lower()), "artist")
        value, notes, work = _clean_value(text[m.end():end])
        track.notes.extend(notes)
        if work and not track.work:
            track.work = work
        if role == "remix":
            remix_by = value
            track.flags.append("remix")
        elif value:
            {"composer": composers, "performer": performers, "artist": artists}[role].append(value)
    track.performer = ", ".join(performers)

    # "A / B by X / Y": pair the works with the credits when the counts match
    if not composers and len(artists) == 1 and "/" in artists[0]:
        credits = [c.strip() for c in artists[0].split("/") if c.strip()]
        expanded = [p.strip() for t in titles for p in t.split("/") if p.strip()]
        if len(expanded) == len(credits) > 1:
            titles = expanded
            return _expand(track, titles, credits, remix_by, ["slash_split"])
        track.flags.append("slash_in_credit")

    track.artist = ", ".join(composers + artists)
    if not (track.artist or track.performer):
        track.flags.append("no_credit")
    return _expand(track, titles, [track.artist] * len(titles), remix_by, [])


def _expand(track: Track, titles: list[str], credits: list[str], remix_by: str, flags: list[str]) -> list[Track]:
    if not titles:
        return [track]
    out = []
    for title, credit in zip(titles, credits):
        title = title.strip(' "')
        out.append(replace(
            track,
            title=_with_remix(title, remix_by) if remix_by else title,
            artist=credit,
            notes=list(track.notes),
            flags=[*track.flags, *flags],
        ))
    return out


def parse_music(cell: str) -> tuple[str, list[Track]]:
    """Return (kind, tracks); kind is 'empty', 'reference' or 'tracks'."""
    cell = cell.strip().replace("“", '"').replace("”", '"')
    if not cell:
        return "empty", []
    if _REFERENCE.match(cell):
        return "reference", [Track(raw_text=cell, notes=[cell.strip("() ")])]
    units = _split_masked(cell, r"\s*;\s*|\s+\|\s+")
    return "tracks", [t for u in units for t in _parse_unit(u)]
