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
from flx.errors import ApiError, BadResponseError, FlxError, InvalidInputError, NetworkError
from flx.trace import Tracer

SCAN_LIMIT = 20  # results per keyword or skill
# At least this long from one search's request to the next, to go easy on the API and stay clear
# of HTTP 429. Measured start to start: a request that took longer already made the gap.
SCAN_PAUSE_S = 1
# A search that fails with one of these is skipped and the scan goes on. Anything else (bad token,
# rate limit that outlasted its retries) would fail for every search, so it stops the scan.
SKIPPABLE = (NetworkError, ApiError, BadResponseError)


@dataclass
class Context:
    """What a command needs from outside. Tests swap in a fake opener, sleep, clock and width."""

    cwd: Path
    config: Path
    tracer: Tracer
    environ: Mapping[str, str]
    opener: Callable[..., Any] | None = None
    sleep: Callable[[float], None] = time.sleep
    now: Callable[[], float] = time.time
    monotonic: Callable[[], float] = time.monotonic
    columns: int | None = None

    def client(self) -> Client:
        token = load_token(self.cwd, self.config, self.environ)
        return Client(token, self.tracer, opener=self.opener, sleep=self.sleep)

    def width(self) -> int:
        return self.columns or shutil.get_terminal_size((100, 24)).columns

    def warn(self, message: str) -> None:
        """Warn on stderr and in the trace. The message may carry API text, so it is cleaned."""
        self.tracer.log("warning", message=message)
        print(f"flx: {render.clean_line(self.tracer.scrub(message))}", file=sys.stderr)


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
    keywords = files.load_keywords(ctx.cwd, ctx.config)
    skills = files.load_skills(ctx.cwd, ctx.config)
    if not keywords and not skills:
        raise InvalidInputError(
            f"Nothing to scan: add search terms to {files.KEYWORDS_FILE} or skill ids to "
            f"{files.SKILLS_FILE} (in {ctx.config} or the current directory)."
        )
    client = ctx.client()
    seen = _load_seen(ctx) if args.only_new else set()
    searches = [("keyword", k, lambda k=k: client.search_projects(k, limit=SCAN_LIMIT)) for k in keywords]
    searches += [("skill", s, lambda s=s: client.search_skill(s, limit=SCAN_LIMIT)) for s in skills]
    batches: list[list[models.Project]] = []
    sources: list[tuple[str, Any]] = []  # (kind, term) of each batch
    failed: dict[str, list] = {"keyword": [], "skill": []}
    started = None
    for kind, term, run in searches:
        if started is not None:
            wait = SCAN_PAUSE_S - (ctx.monotonic() - started)
            if wait > 0:
                ctx.sleep(wait)
        started = ctx.monotonic()
        try:
            batches.append(run())
            sources.append((kind, term))
        except SKIPPABLE as exc:
            failed[kind].append(term)
            ctx.warn(f"{kind} {term!r} failed ({exc}); skipping it.")
    if not batches:
        raise FlxError(f"Every search failed ({len(searches)} of {len(searches)}); nothing to show.")
    projects = models.merge_projects(batches)
    shown = [p for p in projects if p.id not in seen]
    ctx.tracer.log(
        "scan",
        keywords=len(keywords),
        skills=len(skills),
        failed=len(failed["keyword"]) + len(failed["skill"]),
        found=len(projects),
        shown=len(shown),
        **_new_by_term(sources, batches),
    )

    meta = {
        "keywords": keywords,
        "skills": skills,
        "failed_keywords": failed["keyword"],
        "failed_skills": failed["skill"],
        "only_new": args.only_new,
    }
    _print_list(shown, args, ctx, meta, empty="No new projects." if args.only_new else "No projects found.")
    if args.only_new:
        _save_seen(ctx, seen | {p.id for p in projects if p.id is not None})
    return 0


def skills(args: Namespace, ctx: Context) -> int:
    """Look up skill ids by name, for skills.txt. Every skill whose name contains the text."""
    text = args.name.strip()
    if not text:
        raise InvalidInputError("Skill name is empty.")
    found = [s for s in ctx.client().get_skills() if text.casefold() in s.name.casefold()]
    if args.json:
        rows = [{"id": s.id, "name": s.name} for s in found]
        print(render.to_json(_envelope("skills", ctx, name=text, count=len(rows), skills=rows)))
    elif found:
        print("\n".join(f"{s.id:>6}  {render.clean_line(s.name)}" for s in found))
    else:
        print(f"No skills match {text!r}.")
    return 0


def _new_by_term(sources: list[tuple[str, Any]], batches: list[list[models.Project]]) -> dict:
    """How many projects each term added that no earlier term had (trace only; sums to `found`).

    Order-dependent: a project two terms share counts for the first one. A term near 0 on every
    run is a candidate for dropping from the list.
    """
    counts: dict[str, dict[str, int]] = {"new_by_keyword": {}, "new_by_skill": {}}
    seen: set[int] = set()
    for (kind, term), batch in zip(sources, batches):
        new = 0
        for project in batch:
            if project.id not in seen:  # None is never added, so id-less projects always count
                new += 1
            if project.id is not None:
                seen.add(project.id)
        counts[f"new_by_{kind}"][str(term)] = new
    return counts


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
        return files.load_seen(ctx.config)
    except ValueError as exc:
        ctx.warn(f"{ctx.config / files.SEEN_FILE} is unreadable ({exc}); treating every project as new.")
        return set()


def _save_seen(ctx: Context, ids: set[int]) -> None:
    try:
        files.save_seen(ctx.config, ids)
    except OSError as exc:
        ctx.warn(
            f"could not save {ctx.config / files.SEEN_FILE} ({exc.strerror or exc}); "
            "the next --only-new scan may repeat these projects."
        )
