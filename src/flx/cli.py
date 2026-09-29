"""Command-line entry point: argument parsing and dispatch only."""

from __future__ import annotations

import argparse
import sys

from flx import __version__

EXIT_OK = 0
EXIT_NOT_IMPLEMENTED = 2


def _not_built(phase: str):
    def handler(args: argparse.Namespace) -> int:
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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.handler(args)
    except NotImplementedError as exc:
        print(f"flx: {exc}", file=sys.stderr)
        return EXIT_NOT_IMPLEMENTED
