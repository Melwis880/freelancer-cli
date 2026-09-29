"""Command-line entry point: argument parsing and dispatch only."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any

from flx import __version__, commands, files
from flx.errors import FlxError
from flx.render import clean_line
from flx.trace import Tracer

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NOT_IMPLEMENTED = 2


MAX_LIMIT = 100


def _limit(text: str) -> int:
    value = int(text)
    if not 1 <= value <= MAX_LIMIT:
        raise argparse.ArgumentTypeError(f"must be between 1 and {MAX_LIMIT}")
    return value


def _offset(text: str) -> int:
    value = int(text)
    if value < 0:
        raise argparse.ArgumentTypeError("must be 0 or more")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="flx",
        description="Read-only CLI that finds AI and automation jobs on Freelancer.com.",
    )
    parser.add_argument("--version", action="version", version=f"flx {__version__}")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="also print trace lines to stderr (token is always masked)",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>", required=True)

    p = sub.add_parser("whoami", help="check that the token works (shows username only)")
    p.set_defaults(handler=commands.whoami)

    p = sub.add_parser("search", help="search active projects")
    p.add_argument("query", help='search text, e.g. "n8n automation"')
    p.add_argument("--limit", type=_limit, default=20, help=f"max results, 1-{MAX_LIMIT} (default: 20)")
    p.add_argument("--offset", type=_offset, default=0, help="skip this many results (default: 0)")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.set_defaults(handler=commands.search)

    p = sub.add_parser("project", help="show one project in full")
    p.add_argument("project_id", help="numeric project id")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.set_defaults(handler=commands.project)

    p = sub.add_parser("scan", help="search every keyword in keywords.txt, merged and de-duplicated")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument(
        "--only-new",
        action="store_true",
        help="show only projects no earlier --only-new scan has shown (kept in seen.json)",
    )
    p.set_defaults(handler=commands.scan)

    return parser


def main(argv: list[str] | None = None, *, cwd: Path | None = None, **overrides: Any) -> int:
    """Run one command and return its exit code.

    Files live in the config dir (files.py); `cwd` (default: current directory) may override its
    .env.local and keywords.txt. `overrides` are test hooks passed on to commands.Context
    (environ, opener, sleep, now, columns).
    """
    args = build_parser().parse_args(argv)
    cwd = Path.cwd() if cwd is None else Path(cwd)
    environ = overrides.pop("environ", os.environ)
    config = files.config_dir(environ)
    try:
        files.ensure_config(config)
    except OSError as exc:
        print(f"flx: could not create {config} ({exc.strerror or exc}).", file=sys.stderr)
    tracer = Tracer(args.command, config / files.TRACE_DIR, debug=args.debug)
    ctx = commands.Context(cwd=cwd, config=config, tracer=tracer, environ=environ, **overrides)
    options = {k: v for k, v in vars(args).items() if k not in ("handler", "command", "debug")}
    tracer.log("start", options=options)
    started = time.monotonic()

    def elapsed_ms() -> int:
        return round((time.monotonic() - started) * 1000)

    error: Exception | None = None
    try:
        code = args.handler(args, ctx)
    except NotImplementedError as exc:
        code, error = EXIT_NOT_IMPLEMENTED, exc
    except FlxError as exc:
        code, error = EXIT_ERROR, exc
    except Exception as exc:  # a bug: keep the traceback, but leave a trace line first
        tracer.log("end", exit_code=None, duration_ms=elapsed_ms(), error_type=type(exc).__name__)
        raise

    if error is None:
        tracer.log("end", exit_code=code, duration_ms=elapsed_ms())
    else:
        print(f"flx: {clean_line(tracer.scrub(str(error)))}", file=sys.stderr)
        tracer.log(
            "end",
            exit_code=code,
            duration_ms=elapsed_ms(),
            error_type=type(error).__name__,
            error=str(error),
        )
    return code
