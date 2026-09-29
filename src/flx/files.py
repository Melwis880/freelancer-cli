"""Where flx keeps its files, and reading/writing them.

Home is the config dir: `$XDG_CONFIG_HOME/flx`, default `~/.config/flx`. It holds `.env.local`
(token), `keywords.txt`, `seen.json` (project ids only) and `traces/`. It is created on first run,
with a default `keywords.txt`. A `.env.local` or `keywords.txt` in the current directory overrides
the one in the config dir, so a project checkout can carry its own.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Mapping
from pathlib import Path

from flx.errors import InvalidInputError

APP = "flx"
KEYWORDS_FILE = "keywords.txt"
SEEN_FILE = "seen.json"
TRACE_DIR = "traces"
MAX_SEEN = 10_000  # ids only grow, so keeping the highest ones keeps the most recent projects

# Niche terms: broad ones ("openai", "chatbot") pulled in logo and translation jobs.
DEFAULT_KEYWORDS = (
    "n8n",
    "make.com",
    "zapier",
    "langchain",
    "crewai",
    "ai agent development",
    "llm integration",
    "python automation",
    "python web scraping",
)
KEYWORDS_HEADER = (
    "# Search terms for `flx scan`, one per line. Blank lines and lines starting with # are skipped.\n"
)


def config_dir(environ: Mapping[str, str]) -> Path:
    xdg = environ.get("XDG_CONFIG_HOME", "")
    if xdg and Path(xdg).is_absolute():  # the XDG spec says to ignore relative paths
        return Path(xdg) / APP
    home = environ.get("HOME")
    return (Path(home) if home else Path.home()) / ".config" / APP


def ensure_config(config: Path) -> None:
    """Create the config dir (owner-only, it holds the token) and a default keywords.txt."""
    config.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        with (config / KEYWORDS_FILE).open("x", encoding="utf-8") as fh:
            fh.write(KEYWORDS_HEADER + "\n".join(DEFAULT_KEYWORDS) + "\n")
    except FileExistsError:
        pass  # never overwrite the user's list


def find(name: str, cwd: Path, config: Path) -> Path:
    """`cwd/name` if it exists, else `config/name`."""
    local = Path(cwd) / name
    return local if local.is_file() else Path(config) / name


def load_keywords(cwd: Path, config: Path) -> list[str]:
    """One search term per line; blank lines, `#` comments and repeats are skipped."""
    path = find(KEYWORDS_FILE, cwd, config)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise InvalidInputError(
            f"{KEYWORDS_FILE} not found in {cwd} or {config}; create it with one search term per line."
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


def load_seen(config: Path) -> set[int]:
    """Ids shown by earlier `scan --only-new` runs. Raises ValueError if the file is unusable."""
    path = Path(config) / SEEN_FILE
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


def save_seen(config: Path, ids: Iterable[int]) -> None:
    """Replace the file atomically, so an interrupted run never leaves half a file."""
    path = Path(config) / SEEN_FILE
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    keep = sorted(set(ids), reverse=True)[:MAX_SEEN]
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"seen": keep}) + "\n", encoding="utf-8")
    os.replace(tmp, path)
