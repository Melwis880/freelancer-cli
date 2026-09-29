"""Command handlers: gather inputs, call the core, print the result. No filtering or scoring."""

from __future__ import annotations

import shutil
import sys
import time
from argparse import Namespace
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from flx import files, models, render
from flx.auth import load_token
from flx.client import Client
from flx.errors import BadResponseError, InvalidInputError
from flx.trace import Tracer

SCAN_LIMIT = 20  # results per keyword
SCAN_PAUSE_S = 1  # between keywords, to go easy on the API and stay clear of HTTP 429


@dataclass
class Context:
    """What a command needs from outside. Tests swap in a fake opener, sleep, clock and width."""

    base_dir: Path
    tracer: Tracer
    environ: Mapping[str, str]
    opener: Callable[..., Any] | None = None
    sleep: Callable[[float], None] = time.sleep
    now: Callable[[], float] = time.time
    columns: int | None = None

    def client(self) -> Client:
        token = load_token(self.base_dir, self.environ)
        return Client(token, self.tracer, opener=self.opener, sleep=self.sleep)

    def width(self) -> int:
        return self.columns or shutil.get_terminal_size((100, 24)).columns

    def warn(self, message: str) -> None:
        self.tracer.log("warning", message=message)
        print(f"flx: {message}", file=sys.stderr)


def whoami(args: Namespace, ctx: Context) -> int:
    username = ctx.client().get_username()
    if username is None:
        raise BadResponseError("The token works, but Freelancer did not return a username.")
    print(f"Token works. Logged in as {render.clean_line(username)}.")
    return 0


def search(args: Namespace, ctx: Context) -> int:
    query = args.query.strip()
    if not query:
        raise InvalidInputError("Search text is empty.")
    projects = ctx.client().search_projects(query, limit=args.limit, offset=args.offset)
    meta = {"query": query, "limit": args.limit, "offset": args.offset}
    _print_list(projects, args, ctx, meta, empty="No projects found.")
    return 0


def project(args: Namespace, ctx: Context) -> int:
    found = ctx.client().get_project(args.project_id)
    if args.json:
        print(render.to_json(_envelope("project", ctx, project=render.project_dict(found))))
    else:
        print(render.detail(found, width=ctx.width(), now=ctx.now()))
    return 0


def scan(args: Namespace, ctx: Context) -> int:
    client = ctx.client()
    keywords = files.load_keywords(ctx.base_dir)
    seen = _load_seen(ctx) if args.only_new else set()
    batches = []
    for i, keyword in enumerate(keywords):
        if i:
            ctx.sleep(SCAN_PAUSE_S)
        batches.append(client.search_projects(keyword, limit=SCAN_LIMIT))
    projects = models.merge_projects(batches)
    shown = [p for p in projects if p.id not in seen]
    ctx.tracer.log("scan", keywords=len(keywords), found=len(projects), shown=len(shown))

    meta = {"keywords": keywords, "only_new": args.only_new}
    _print_list(shown, args, ctx, meta, empty="No new projects." if args.only_new else "No projects found.")
    if args.only_new:
        _save_seen(ctx, seen | {p.id for p in projects if p.id is not None})
    return 0


def _print_list(projects, args, ctx: Context, meta: dict, *, empty: str) -> None:
    if args.json:
        rows = [render.project_dict(p) for p in projects]
        print(render.to_json(_envelope(args.command, ctx, **meta, count=len(rows), projects=rows)))
    elif projects:
        print(render.table(projects, width=ctx.width(), now=ctx.now()))
    else:
        print(empty)


def _envelope(command: str, ctx: Context, **fields: Any) -> dict:
    return {"command": command, "generated_at": render.iso_utc(ctx.now()), **fields}


def _load_seen(ctx: Context) -> set[int]:
    try:
        return files.load_seen(ctx.base_dir)
    except ValueError as exc:
        ctx.warn(f"{files.SEEN_FILE} is unreadable ({exc}); treating every project as new.")
        return set()


def _save_seen(ctx: Context, ids: set[int]) -> None:
    try:
        files.save_seen(ctx.base_dir, ids)
    except OSError as exc:
        ctx.warn(
            f"could not save {files.SEEN_FILE} ({exc.strerror or exc}); "
            "the next --only-new scan may repeat these projects."
        )
