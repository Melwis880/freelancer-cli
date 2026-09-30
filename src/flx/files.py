"""Where flx keeps its files, and reading/writing them.

Home is the config dir: `$XDG_CONFIG_HOME/flx`, default `~/.config/flx`. It holds `.env.local`
(token), `keywords.txt`, `skills.txt`, `seen.json` (project ids only) and `traces/`. It is created
on first run, with a default `keywords.txt` and `skills.txt`. A `.env.local`, `keywords.txt` or
`skills.txt` in the current directory overrides the one in the config dir, so a project checkout
can carry its own.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Iterable, Mapping
from pathlib import Path

from flx.errors import InvalidInputError

APP = "flx"
KEYWORDS_FILE = "keywords.txt"
SKILLS_FILE = "skills.txt"
SEEN_FILE = "seen.json"
TRACE_DIR = "traces"
MAX_SEEN = 10_000  # ids only grow, so keeping the highest ones keeps the most recent projects
# Caps for files that may come from the current directory, i.e. from a checkout flx does not own:
# a planted FIFO, /dev/zero or huge file cannot hang flx, and a huge keyword list cannot turn
# into thousands of API calls under the user's token.
MAX_FILE_BYTES = 64 * 1024
MAX_TERMS = 50  # per file: keywords.txt and skills.txt each

# Single niche terms. Broad ones ("openai", "chatbot") pulled in logo and translation jobs, and the
# API matches multi-word terms loosely ("llm integration" found the phrase in 1 of 20 results,
# quotes are ignored), filling the list with unrelated jobs.
DEFAULT_KEYWORDS = (
    "n8n",
    "make.com",
    "zapier",
    "langchain",
    "crewai",
)
KEYWORDS_HEADER = (
    "# Search terms for `flx scan`, one per line. Blank lines and lines starting with # are skipped.\n"
)
# Freelancer skill ids: searching by skill matches exactly, where multi-word text does not. Picked
# by a live check (2026-09-30): "AI Automation" (3380) and "Workflow Automation" (3381) came back
# about half video, sales or ERP work, so they are left out.
DEFAULT_SKILLS = (
    (3028, "AI Agents"),
    (3132, "Agentic AI"),
    (2916, "AI Chatbot Development"),
    (3101, "LLM Integration"),
    (3100, "Retrieval-Augmented Generation (RAG)"),
    (95, "Web Scraping"),
)
SKILLS_HEADER = (
    "# Freelancer skill ids for `flx scan`, one per line; text after # is a note.\n"
    "# Find more with: flx skills \"<name>\"\n"
)
_SKILL_ID = re.compile(r"[0-9]{1,9}")


def config_dir(environ: Mapping[str, str]) -> Path:
    xdg = environ.get("XDG_CONFIG_HOME", "")
    if xdg and Path(xdg).is_absolute():  # the XDG spec says to ignore relative paths
        return Path(xdg) / APP
    home = environ.get("HOME")
    return (Path(home) if home else Path.home()) / ".config" / APP


def ensure_config(config: Path) -> None:
    """Create the config dir (owner-only, it holds the token), a default keywords.txt and skills.txt.

    A dir that already exists, e.g. from `mkdir -p` with umask 002, is tightened to 700.
    """
    config.mkdir(mode=0o700, parents=True, exist_ok=True)
    owner_only(config, 0o700)
    skills = "".join(f"{skill_id}  # {name}\n" for skill_id, name in DEFAULT_SKILLS)
    for name, text in (
        (KEYWORDS_FILE, KEYWORDS_HEADER + "\n".join(DEFAULT_KEYWORDS) + "\n"),
        (SKILLS_FILE, SKILLS_HEADER + skills),
    ):
        try:
            with (config / name).open("x", encoding="utf-8") as fh:
                fh.write(text)
        except FileExistsError:
            pass  # never overwrite the user's list


def owner_only(path: Path, mode: int) -> None:
    """chmod `path` to `mode` if group or others have any access (umask 002 leaves 775/664)."""
    if Path(path).stat().st_mode & 0o077:
        Path(path).chmod(mode)


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
    """One search term per line; blank lines, `#` comments and repeats (any case) are skipped."""
    path, lines = _lines(KEYWORDS_FILE, cwd, config)
    keywords: list[str] = []
    seen: set[str] = set()
    for line in lines:
        keyword = line.strip()
        if keyword and not keyword.startswith("#") and keyword.casefold() not in seen:
            seen.add(keyword.casefold())
            keywords.append(keyword)
    return _capped(keywords, path, "keywords")


def load_skills(cwd: Path, config: Path) -> list[int]:
    """One skill id per line; anything after `#` is a note. Blank lines and repeats are skipped."""
    path, lines = _lines(SKILLS_FILE, cwd, config)
    skills: list[int] = []
    for number, line in enumerate(lines, 1):
        text = line.partition("#")[0].strip()
        if not text:
            continue
        if not _SKILL_ID.fullmatch(text) or int(text) == 0:
            raise InvalidInputError(
                f"{path} line {number}: {text[:40]!r} is not a skill id; find ids with `flx skills <name>`."
            )
        if int(text) not in skills:
            skills.append(int(text))
    return _capped(skills, path, "skills")


def _lines(name: str, cwd: Path, config: Path) -> tuple[Path, list[str]]:
    """Lines of `name` from cwd or the config dir; a missing file has none."""
    path = find(name, cwd, config)
    try:
        return path, read_small(path).splitlines()
    except FileNotFoundError:
        return path, []
    except (OSError, ValueError) as exc:
        raise InvalidInputError(f"Could not read {path} ({reason(exc)}).") from None


def _capped(items: list, path: Path, what: str) -> list:
    if len(items) > MAX_TERMS:
        raise InvalidInputError(
            f"{path} has {len(items)} {what}; scan takes at most {MAX_TERMS}, one API call each."
        )
    return items


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
