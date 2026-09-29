"""Where flx keeps its files, and reading/writing them.

Home is the config dir: `$XDG_CONFIG_HOME/flx`, default `~/.config/flx`. It holds `.env.local`
(token), `keywords.txt`, `seen.json` (project ids only) and `traces/`. It is created on first run,
with a default `keywords.txt`. A `.env.local` or `keywords.txt` in the current directory overrides
the one in the config dir, so a project checkout can carry its own.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterable, Mapping
from pathlib import Path

from flx.errors import InvalidInputError

APP = "flx"
KEYWORDS_FILE = "keywords.txt"
SEEN_FILE = "seen.json"
TRACE_DIR = "traces"
MAX_SEEN = 10_000  # ids only grow, so keeping the highest ones keeps the most recent projects
# Caps for files that may come from the current directory, i.e. from a checkout flx does not own:
# a planted FIFO, /dev/zero or huge file cannot hang flx, and a huge keyword list cannot turn
# into thousands of API calls under the user's token.
MAX_FILE_BYTES = 64 * 1024
MAX_KEYWORDS = 50

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
    """Create the config dir (owner-only, it holds the token) and a default keywords.txt.

    A dir that already exists, e.g. from `mkdir -p` with umask 002, is tightened to 700.
    """
    config.mkdir(mode=0o700, parents=True, exist_ok=True)
    if config.stat().st_mode & 0o077:
        config.chmod(0o700)
    try:
        with (config / KEYWORDS_FILE).open("x", encoding="utf-8") as fh:
            fh.write(KEYWORDS_HEADER + "\n".join(DEFAULT_KEYWORDS) + "\n")
    except FileExistsError:
        pass  # never overwrite the user's list


def find(name: str, cwd: Path, config: Path) -> Path:
    """`cwd/name` if it exists, else `config/name`."""
    local = Path(cwd) / name
    return local if local.is_file() else Path(config) / name


def read_small(path: Path) -> str:
    """Text of a small config file.

    Raises FileNotFoundError if it is missing, OSError if it cannot be read, and ValueError if it
    is not a regular file, is over MAX_FILE_BYTES or is not UTF-8.
    """
    path = Path(path)
    if path.exists() and not path.is_file():
        raise ValueError("not a regular file")
    with path.open("rb") as fh:
        data = fh.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise ValueError(f"larger than {MAX_FILE_BYTES // 1024} KiB")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("not UTF-8 text") from None


def reason(exc: Exception) -> str:
    """Short cause of a read_small failure, for error messages."""
    return getattr(exc, "strerror", None) or str(exc)


def load_keywords(cwd: Path, config: Path) -> list[str]:
    """One search term per line; blank lines, `#` comments and repeats are skipped."""
    path = find(KEYWORDS_FILE, cwd, config)
    try:
        text = read_small(path)
    except FileNotFoundError:
        raise InvalidInputError(
            f"{KEYWORDS_FILE} not found in {cwd} or {config}; create it with one search term per line."
        ) from None
    except (OSError, ValueError) as exc:
        raise InvalidInputError(f"Could not read {path} ({reason(exc)}).") from None
    keywords: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        keyword = line.strip()
        if keyword and not keyword.startswith("#") and keyword.casefold() not in seen:
            seen.add(keyword.casefold())
            keywords.append(keyword)
    if not keywords:
        raise InvalidInputError(f"{path} has no keywords; add one search term per line.")
    if len(keywords) > MAX_KEYWORDS:
        raise InvalidInputError(
            f"{path} has {len(keywords)} keywords; scan takes at most {MAX_KEYWORDS}, "
            "one API call each."
        )
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
    """Replace the file atomically, so an interrupted run never leaves half a file.

    The temp file gets a fresh random name (created exclusively), so a planted symlink cannot
    redirect the write and two runs at once cannot clobber each other's temp file.
    """
    path = Path(config) / SEEN_FILE
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    keep = sorted(set(ids), reverse=True)[:MAX_SEEN]
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=SEEN_FILE + ".", suffix=".tmp", delete=False
    ) as fh:
        fh.write(json.dumps({"seen": keep}) + "\n")
    try:
        os.replace(fh.name, path)
    except OSError:
        os.unlink(fh.name)
        raise
