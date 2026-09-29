"""Test doubles: a fake HTTP opener that never touches the network, plus sample API data."""

import contextlib
import email.message
import io
import json
import tempfile
import types
import urllib.error
from pathlib import Path

import _path  # noqa: F401

from flx import cli
from flx.client import Client
from flx.trace import Tracer

TOKEN = "tok-SECRET-5f3a9c1e7b2d"
NOW = 1790000000 + 2 * 3600  # two hours after project 101 was posted

SEARCH_RESULT = {
    "projects": [
        {
            "id": 101,
            "title": "Build an n8n workflow",
            "seo_url": "n8n/build-an-n8n-workflow",
            "type": "fixed",
            "budget": {"minimum": 30, "maximum": 250},
            "currency": {"code": "USD", "sign": "$"},
            "bid_stats": {"bid_count": 12, "bid_avg": 140.5},
            "time_submitted": 1790000000,
            "description": "Connect a CRM to Slack with n8n.",
            "preview_description": "Connect a CRM...",
            "owner_info": {"country": {"name": "Germany"}, "status": {"payment_verified": True}},
        },
        {
            "id": 102,
            "title": "Python scraper",
            "seo_url": "python/python-scraper",
            "type": "hourly",
            "budget": {"minimum": 15, "maximum": 25},
            "currency": {"code": "EUR"},
            "bid_stats": {"bid_count": 3, "bid_avg": 20},
            "time_submitted": 1790000500,
            "preview_description": "Scrape product pages.",
            "owner_info": {"country": {"name": "Canada"}, "status": {"payment_verified": False}},
        },
    ],
    "total_count": 2,
}


class FakeResponse:
    def __init__(self, body, status=200):
        self.status = status
        self._body = body if isinstance(body, bytes) else json.dumps(body).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def ok(result):
    return FakeResponse({"status": "success", "result": result})


def http_error(code, body=b"", headers=None):
    message = email.message.Message()
    for key, value in (headers or {}).items():
        message[key] = value
    if not isinstance(body, bytes):
        body = json.dumps(body).encode()
    return urllib.error.HTTPError("https://fake.invalid/", code, "error", message, io.BytesIO(body))


class FakeOpener:
    """Stands in for urlopen: records every request and replays queued outcomes in order."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.requests = []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def make_tracer(test, *, stream=None):
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    return Tracer("test", Path(tmp.name) / "traces", debug=stream is not None, stream=stream)


def make_client(test, *outcomes, stream=None):
    """A Client wired to a FakeOpener, a recording sleep and a tracer in a temp dir."""
    tracer = make_tracer(test, stream=stream)
    opener = FakeOpener(*outcomes)
    sleeps = []
    client = Client(TOKEN, tracer, opener=opener, sleep=sleeps.append)
    return types.SimpleNamespace(client=client, opener=opener, sleeps=sleeps, tracer=tracer)


def temp_dir(test):
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    return Path(tmp.name)


def run_cli(test, argv, *outcomes, environ=None, keywords=None, base_dir=None, columns=100):
    """Run flx in-process against a fake API, in a temp base dir with a token in its environment.

    A request the test did not queue an outcome for fails the test loudly (IndexError).
    """
    base_dir = base_dir or temp_dir(test)
    if keywords is not None:
        (base_dir / "keywords.txt").write_text(keywords, encoding="utf-8")
    opener = FakeOpener(*outcomes)
    sleeps = []
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(
            argv,
            base_dir=base_dir,
            environ={"FREELANCER_TOKEN": TOKEN} if environ is None else environ,
            opener=opener,
            sleep=sleeps.append,
            now=lambda: NOW,
            columns=columns,
        )
    return types.SimpleNamespace(
        code=code, out=out.getvalue(), err=err.getvalue(), opener=opener, sleeps=sleeps, base_dir=base_dir
    )


def trace_lines(base_dir):
    return [
        line
        for path in sorted((Path(base_dir) / "traces").glob("*.jsonl"))
        for line in path.read_text(encoding="utf-8").splitlines()
    ]


def trace_text(tracer):
    return "".join(p.read_text(encoding="utf-8") for p in sorted(tracer.trace_dir.glob("*.jsonl")))


def read_trace(tracer):
    return [json.loads(line) for line in trace_text(tracer).splitlines()]
