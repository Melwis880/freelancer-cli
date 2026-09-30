"""Turn projects into text for people (table, detail view) or JSON for programs.

Text output drops control and formatting characters from API strings, so a project title cannot
move the cursor, recolour the terminal or reorder text. JSON output escapes them instead
(`ensure_ascii`), which also keeps it printable whatever the terminal encoding.
"""

from __future__ import annotations

import json
import re
import textwrap
import unicodedata
from dataclasses import asdict
from datetime import datetime, timezone
from typing import NamedTuple

from flx import SCHEMA_VERSION
from flx.models import Project

ELLIPSIS = "…"
GAP = "  "
MIN_TITLE = 24


class Column(NamedTuple):
    header: str
    cap: int  # widest the column may get
    right: bool  # right-aligned
    drop: int  # order in which a narrow terminal hides it; 0 = always shown


# TITLE comes last and takes whatever width is left. Type shows as "/h" on hourly budgets.
COLUMNS = (
    Column("ID", 12, True, 0),
    Column("AGE", 4, True, 5),
    Column("BUDGET", 20, True, 0),
    Column("BIDS", 5, True, 4),
    Column("AVG", 8, True, 1),
    Column("COUNTRY", 14, False, 2),
    Column("VERIFIED", 8, False, 3),
)
_DROP = {"Cf": "", "Cs": "", "Cc": " ", "Zl": " ", "Zp": " "}


def to_json(payload: dict) -> str:
    return json.dumps({"schema_version": SCHEMA_VERSION, **payload}, indent=2)


def project_dict(project: Project) -> dict:
    data = asdict(project)
    data["time_submitted"] = iso_utc(project.time_submitted)
    return data


def iso_utc(timestamp: float | None) -> str | None:
    moment = _utc(timestamp)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ") if moment else None


def table(projects: list[Project], *, width: int, now: float) -> str:
    """One row per project, no wider than `width` unless even ID + BUDGET + TITLE cannot fit."""
    rows = [[clean_line(cell) for cell in _cells(p, now)] for p in projects]
    widths = [
        min(col.cap, max([display_width(col.header)] + [display_width(row[i]) for row in rows]))
        for i, col in enumerate(COLUMNS)
    ]
    shown = list(range(len(COLUMNS)))

    def title_room() -> int:
        return width - sum(widths[i] + len(GAP) for i in shown)

    for i in sorted((i for i, col in enumerate(COLUMNS) if col.drop), key=lambda i: COLUMNS[i].drop):
        if title_room() >= MIN_TITLE:
            break
        shown.remove(i)
    title_width = max(title_room(), 8)

    def line(cells: list[str], title: str) -> str:
        fixed = [_pad(fit(cells[i], widths[i]), widths[i], COLUMNS[i].right) for i in shown]
        return GAP.join(fixed + [fit(title, title_width)])

    lines = [line([col.header for col in COLUMNS], "TITLE")]
    lines += [line(row, clean_line(p.title or "-")) for row, p in zip(rows, projects)]
    return "\n".join(lines)


def detail(project: Project, *, width: int, now: float) -> str:
    p = project
    posted = _utc(p.time_submitted)
    fields = [
        ("ID", str(p.id) if p.id is not None else "-"),
        ("Link", clean_line(p.url or "-")),
        ("Type", clean_line(p.type or "-")),
        ("Budget", _budget(p)),
        ("Bids", _bids(p)),
        ("Posted", f"{posted:%Y-%m-%d %H:%M} UTC ({age(p.time_submitted, now)} ago)" if posted else "-"),
        ("Client", _client(p)),
        ("Skills", clean_line(", ".join(p.skills)) if p.skills else "-"),
    ]
    head = clean_line(p.title or "(no title)")
    body = "\n".join(f"{label:<8}{value}" for label, value in fields)
    description = clean_block(p.description or "(no description)")
    wrapped = "\n".join(
        textwrap.fill(para, max(width, 20)) if para else "" for para in description.split("\n")
    )
    return f"{head}\n\n{body}\n\nDescription\n{wrapped}"


def age(timestamp: int | None, now: float) -> str:
    if timestamp is None:
        return "-"
    seconds = max(0, int(now - timestamp))
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"


def clean_line(text: str) -> str:
    """One terminal-safe line: control and formatting characters removed, whitespace collapsed."""
    return " ".join(_strip_controls(text).split())


def clean_block(text: str) -> str:
    """Terminal-safe text that keeps its line breaks."""
    lines = re.split("\r\n|[\r\n  ]", text)
    return "\n".join(_strip_controls(line).rstrip() for line in lines).strip("\n")


def _strip_controls(text: str) -> str:
    return "".join(_DROP.get(unicodedata.category(c), c) for c in text)


def display_width(text: str) -> int:
    return sum(_char_width(c) for c in text)


def fit(text: str, width: int) -> str:
    """Cut `text` to at most `width` terminal columns, marking the cut with an ellipsis."""
    if display_width(text) <= width:
        return text
    out, used = [], 0
    for c in text:
        w = _char_width(c)
        if used + w > width - 1:
            break
        out.append(c)
        used += w
    return "".join(out) + ELLIPSIS


def _cells(p: Project, now: float) -> list[str]:
    return [
        str(p.id) if p.id is not None else "-",
        age(p.time_submitted, now),
        _budget(p),
        str(p.bid_count) if p.bid_count is not None else "-",
        _amount(p.bid_avg, decimals=0) or "-",
        p.client_country or "-",
        {True: "yes", False: "no"}.get(p.payment_verified, "-"),
    ]


def _budget(p: Project) -> str:
    low, high = _amount(p.budget_min), _amount(p.budget_max)
    if low is None and high is None:
        return "-"
    span = f"{low}-{high}" if low and high and low != high else (low or high)
    return _with_currency(span, p) + ("/h" if p.type == "hourly" else "")


def _bids(p: Project) -> str:
    count = str(p.bid_count) if p.bid_count is not None else "-"
    average = _amount(p.bid_avg)
    return f"{count} (average {_with_currency(average, p)})" if average else count


def _with_currency(amount: str, p: Project) -> str:
    unit = clean_line(p.currency or "")
    return f"{amount} {unit}" if unit else amount


def _client(p: Project) -> str:
    verified = {True: "payment verified", False: "payment not verified"}
    return f"{clean_line(p.client_country or 'country unknown')}, " + verified.get(
        p.payment_verified, "payment status unknown"
    )


def _amount(value: float | None, decimals: int | None = None) -> str | None:
    if value is None:
        return None
    if decimals is None:
        decimals = 0 if float(value).is_integer() else 2
    return f"{value:,.{decimals}f}"


def _utc(timestamp: float | None) -> datetime | None:
    if timestamp is None:
        return None
    try:
        return datetime.fromtimestamp(timestamp, timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _pad(text: str, width: int, right: bool) -> str:
    space = " " * max(0, width - display_width(text))
    return space + text if right else text + space


def _char_width(c: str) -> int:
    if unicodedata.combining(c):
        return 0
    return 2 if unicodedata.east_asian_width(c) in ("W", "F") else 1
