"""Local files: `keywords.txt` (read) and `state/seen.json` (read and written, project ids only)."""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from pathlib import Path

from flx.errors import InvalidInputError

KEYWORDS_FILE = "keywords.txt"
SEEN_FILE = Path("state") / "seen.json"
MAX_SEEN = 10_000  # ids only grow, so keeping the highest ones keeps the most recent projects


def load_keywords(base_dir: Path) -> list[str]:
    """One search term per line; blank lines, `#` comments and repeats are skipped."""
    path = Path(base_dir) / KEYWORDS_FILE
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise InvalidInputError(
            f"{KEYWORDS_FILE} not found in {path.parent}; create it with one search term per line."
        ) from None
    except (OSError, UnicodeDecodeError):
        raise InvalidInputError(f"Could not read {path}.") from None
    keywords: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        keyword = line.strip()
        if keyword and not keyword.startswith("#") and keyword.casefold() not in seen:
            seen.add(keyword.casefold())
            keywords.append(keyword)
    if not keywords:
        raise InvalidInputError(f"{path} has no keywords; add one search term per line.")
    return keywords


def load_seen(base_dir: Path) -> set[int]:
    """Ids shown by earlier `scan --only-new` runs. Raises ValueError if the file is unusable."""
    path = Path(base_dir) / SEEN_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return set()
    except OSError as exc:
        raise ValueError(exc.strerror or str(exc)) from None
    ids = data.get("seen") if isinstance(data, dict) else None
    if not isinstance(ids, list) or not all(type(i) is int for i in ids):
        raise ValueError("unexpected format")
    return set(ids)


def save_seen(base_dir: Path, ids: Iterable[int]) -> None:
    """Replace the file atomically, so an interrupted run never leaves half a file."""
    path = Path(base_dir) / SEEN_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    keep = sorted(set(ids), reverse=True)[:MAX_SEEN]
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"seen": keep}) + "\n", encoding="utf-8")
    os.replace(tmp, path)
