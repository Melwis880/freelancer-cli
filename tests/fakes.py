"""Test doubles: a fake HTTP opener that never touches the network, plus sample API data."""

import email.message
import io
import json
import tempfile
import types
import urllib.error
from pathlib import Path

import _path  # noqa: F401

from flx.client import Client
from flx.trace import Tracer

TOKEN = "tok-SECRET-5f3a9c1e7b2d"

SEARCH_RESULT = {
    "projects": [
        {
            "id": 101,
            "owner_id": 7,
            "title": "Build an n8n workflow",
            "seo_url": "n8n/build-an-n8n-workflow",
            "type": "fixed",
            "budget": {"minimum": 30, "maximum": 250},
            "currency": {"code": "USD", "sign": "$"},
            "bid_stats": {"bid_count": 12, "bid_avg": 140.5},
            "time_submitted": 1790000000,
            "description": "Connect a CRM to Slack with n8n.",
            "preview_description": "Connect a CRM...",
        },
        {
            "id": 102,
            "owner_id": 8,
            "title": "Python scraper",
            "seo_url": "python/python-scraper",
            "type": "hourly",
            "budget": {"minimum": 15, "maximum": 25},
            "currency": {"code": "EUR"},
            "bid_stats": {"bid_count": 3, "bid_avg": 20},
            "time_submitted": 1790000500,
            "preview_description": "Scrape product pages.",
        },
    ],
    "users": {
        "7": {"id": 7, "location": {"country": {"name": "Germany"}}, "status": {"payment_verified": True}},
        "8": {"id": 8, "location": {"country": {"name": "Canada"}}, "status": {"payment_verified": False}},
    },
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


def trace_text(tracer):
    return "".join(p.read_text(encoding="utf-8") for p in sorted(tracer.trace_dir.glob("*.jsonl")))


def read_trace(tracer):
    return [json.loads(line) for line in trace_text(tracer).splitlines()]
