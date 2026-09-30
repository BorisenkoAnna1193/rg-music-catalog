"""Find and flatten routine-music tables in Wikipedia article HTML.

Gymnast articles usually carry two kinds of tables that mention music:

* ``routine``      - "Year | Apparatus | Music title", one row per routine;
* ``competition``  - "Year | Competition Description | Location | Music |
  Apparatus | ...", e.g. the Olympic results table. It is a useful second
  source for cross-checking the first one.

The tables are hand-edited, so their layout drifts from page to page:
years spanning several rows (``rowspan``), a year sitting alone in its own
row, footnote markers, several tracks separated by ``<br>`` and so on.
We expand every table into a plain rectangular grid first and only then
map columns by their header text, so the parser does not depend on one
particular layout.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, Tag

LINE_BREAK = " | "  # what <br> inside a cell turns into
YEAR_RE = re.compile(r"^(19|20)\d{2}$")


@dataclass
class TableInfo:
    index: int
    kind: str  # routine | competition | other
    headers: list[str]
    n_rows: int


@dataclass
class MusicRow:
    table_index: int
    table_kind: str
    row_index: int
    year: str
    apparatus: str
    music: str
    competition: str = ""
    location: str = ""
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- cell text
def cell_text(cell: Tag) -> str:
    """Visible text of a cell without footnotes; <br> becomes LINE_BREAK."""
    for junk in cell.select("sup.reference, sup.noprint, span.mw-ref, style, .sortkey"):
        junk.decompose()
    for br in cell.find_all("br"):
        br.replace_with(LINE_BREAK)
    text = cell.get_text("")
    text = text.replace("\xa0", " ")
    text = re.sub(r"\[(\d+|citation needed|note \d+|[a-z])\]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if "|" not in text:
        return text
    # Drop empty pieces, and glue back pieces where <br> was only a visual
    # wrap, not a track separator: "Title<br>by Artist", "Title<br>(from X)".
    parts: list[str] = []
    for piece in (p.strip() for p in text.split("|")):
        if not piece:
            continue
        if parts and CONTINUATION_RE.match(piece):
            parts[-1] = f"{parts[-1]} {piece}"
        else:
            parts.append(piece)
    return LINE_BREAK.join(parts)


CONTINUATION_RE = re.compile(r"^(by|from|feat\.?|ft\.?|performed|composed|arr\.?)\b|^\(", re.I)
PLACEHOLDERS = {"—", "–", "-", "?", "n/a", "unknown", "tba"}


def _own_rows(table: Tag) -> list[Tag]:
    """<tr> elements of this table, skipping rows of nested tables."""
    return [tr for tr in table.find_all("tr") if tr.find_parent("table") is table]


# ---------------------------------------------------------------- grid
def expand_table(table: Tag) -> list[list[tuple[str, bool]]]:
    """Expand rowspan/colspan into a rectangular-ish grid.

    Each grid cell is ``(text, is_header)``. Rows keep their natural length,
    so a row that is genuinely shorter than the header stays shorter - that
    is a signal we use later instead of silently padding it.
    """
    grid: list[list[tuple[str, bool]]] = []
    pending: dict[int, tuple[tuple[str, bool], int]] = {}  # col -> (value, rows left)

    for tr in _own_rows(table):
        row: list[tuple[str, bool]] = []
        cells = tr.find_all(["td", "th"], recursive=False)
        col = 0
        ci = 0
        while ci < len(cells) or col in pending:
            if col in pending:
                value, left = pending[col]
                row.append(value)
                if left <= 1:
                    del pending[col]
                else:
                    pending[col] = (value, left - 1)
                col += 1
                continue
            cell = cells[ci]
            ci += 1
            value = (cell_text(cell), cell.name == "th")
            rowspan = _int_attr(cell, "rowspan")
            colspan = _int_attr(cell, "colspan")
            for _ in range(colspan):
                row.append(value)
                if rowspan > 1:
                    pending[col] = (value, rowspan - 1)
                col += 1
        grid.append(row)
    return grid


def _int_attr(cell: Tag, name: str) -> int:
    try:
        return max(1, int(str(cell.get(name, "1")).strip().rstrip(";")))
    except ValueError:
        return 1


# ---------------------------------------------------------------- classify
def _find_col(headers: list[str], *needles: str) -> int | None:
    for i, h in enumerate(headers):
        if any(n in h for n in needles):
            return i
    return None


def classify(headers: list[str]) -> str:
    h = [x.lower() for x in headers]
    has_music = _find_col(h, "music") is not None
    if has_music and _find_col(h, "competition") is not None:
        return "competition"
    if has_music and _find_col(h, "apparatus") is not None and _find_col(h, "year") is not None:
        return "routine"
    return "other"


def _header_row(grid: list[list[tuple[str, bool]]]) -> int | None:
    for i, row in enumerate(grid):
        if row and all(is_th for _, is_th in row) and len(row) > 1:
            return i
    return None


# ---------------------------------------------------------------- extract
def extract_music_tables(html: str) -> tuple[list[TableInfo], list[MusicRow]]:
    soup = BeautifulSoup(html, "lxml")
    tables = soup.select("table.wikitable") or soup.find_all("table")

    infos: list[TableInfo] = []
    rows: list[MusicRow] = []
    for t_idx, table in enumerate(tables):
        grid = expand_table(table)
        h_idx = _header_row(grid)
        if h_idx is None:
            continue
        headers = [text for text, _ in grid[h_idx]]
        kind = classify(headers)
        infos.append(TableInfo(t_idx, kind, headers, len(grid) - h_idx - 1))
        if kind == "other":
            continue
        rows.extend(_rows_from_grid(t_idx, kind, headers, grid[h_idx + 1 :]))
    return infos, rows


def _rows_from_grid(t_idx, kind, headers, body) -> list[MusicRow]:
    h = [x.lower() for x in headers]
    c_year = _find_col(h, "year")
    c_app = _find_col(h, "apparatus")
    c_music = _find_col(h, "music")
    c_comp = _find_col(h, "competition")
    c_loc = _find_col(h, "location")
    width = len(headers)

    out: list[MusicRow] = []
    last_year = ""
    for r_idx, raw in enumerate(body):
        cells = [text for text, _ in raw]
        notes: list[str] = []

        # A year alone in its own row (no rowspan): remember it and move on.
        non_empty = {c for c in cells if c}
        if len(non_empty) == 1 and YEAR_RE.match(next(iter(non_empty))):
            last_year = next(iter(non_empty))
            continue

        # Row shorter than the header: the year cell is missing on the left.
        if len(cells) < width and c_year == 0 and not (cells and YEAR_RE.match(cells[0])):
            missing = width - len(cells)
            cells = [last_year] + [""] * (missing - 1) + cells
            notes.append("year_carried_over")
        cells += [""] * (width - len(cells))

        def get(c):
            return cells[c] if c is not None and c < len(cells) else ""

        year, app, music = get(c_year), get(c_app), get(c_music)
        if music.lower() in PLACEHOLDERS:
            music = ""
        if YEAR_RE.match(year):
            last_year = year
        elif year:
            notes.append("year_not_a_year")
        if not app and not music:
            continue
        if not music:
            notes.append("music_empty")
        out.append(
            MusicRow(
                table_index=t_idx,
                table_kind=kind,
                row_index=r_idx,
                year=year,
                apparatus=app,
                music=music,
                competition=get(c_comp),
                location=get(c_loc),
                notes=notes,
            )
        )
    return out
