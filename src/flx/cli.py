"""Command-line entry point: argument parsing and dispatch only."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from flx import __version__
from flx.errors import FlxError
from flx.trace import Tracer

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NOT_IMPLEMENTED = 2

TRACE_DIR = "traces"


def _not_built(phase: str):
    def handler(args: argparse.Namespace, tracer: Tracer, base_dir: Path) -> int:
        raise NotImplementedError(f"'{args.command}' is not built yet ({phase}).")

    return handler


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
    p.set_defaults(handler=_not_built("Phase 2"))

    p = sub.add_parser("search", help="search active projects")
    p.add_argument("query", help='search text, e.g. "n8n automation"')
    p.add_argument("--limit", type=int, default=20, help="max results (default: 20)")
    p.add_argument("--offset", type=int, default=0, help="skip this many results (default: 0)")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.set_defaults(handler=_not_built("Phase 2"))

    p = sub.add_parser("project", help="show one project in full")
    p.add_argument("project_id", help="numeric project id")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.set_defaults(handler=_not_built("Phase 2"))

    p = sub.add_parser("scan", help="search every keyword in keywords.txt, merged and de-duplicated")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--only-new", action="store_true", help="show only projects not seen before")
    p.set_defaults(handler=_not_built("Phase 2"))

    return parser


def main(argv: list[str] | None = None, *, base_dir: Path | None = None) -> int:
    """Run one command. `base_dir` holds .env.local and traces/ (default: current directory)."""
    args = build_parser().parse_args(argv)
    base_dir = Path.cwd() if base_dir is None else Path(base_dir)
    tracer = Tracer(args.command, base_dir / TRACE_DIR, debug=args.debug)
    options = {k: v for k, v in vars(args).items() if k not in ("handler", "command", "debug")}
    tracer.log("start", options=options)
    started = time.monotonic()

    def elapsed_ms() -> int:
        return round((time.monotonic() - started) * 1000)

    error: Exception | None = None
    try:
        code = args.handler(args, tracer, base_dir)
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
        print(f"flx: {tracer.scrub(str(error))}", file=sys.stderr)
        tracer.log(
            "end",
            exit_code=code,
            duration_ms=elapsed_ms(),
            error_type=type(error).__name__,
            error=str(error),
        )
    return code
