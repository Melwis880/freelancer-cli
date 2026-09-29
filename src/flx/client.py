"""Read-only HTTP client for the Freelancer REST API.

`request` refuses every method except GET before anything is built, and there is no way to pass a
request body. Redirects are not followed, so the token header is never re-sent to another URL.
HTTP 429 is retried with backoff (up to 3 times) and a timeout once; nothing else is retried.
"""

from __future__ import annotations

import http.client
import json
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

from flx import __version__, models
from flx.auth import check_token
from flx.errors import (
    ApiError,
    AuthError,
    BadResponseError,
    FlxError,
    InvalidInputError,
    NetworkError,
    NotFoundError,
    RateLimitError,
    ReadOnlyError,
)
from flx.trace import Tracer

API_BASE = "https://www.freelancer.com/api"
AUTH_HEADER = "Freelancer-OAuth-V1"
TIMEOUT_S = 20
BACKOFF_S = (1, 2, 4)  # one wait per retry after HTTP 429
MAX_RETRY_AFTER_S = 10
TIMEOUT_RETRIES = 1  # a slow API day usually recovers on the next try
TIMEOUT_WAIT_S = 2
MAX_BODY_BYTES = 10 * 1024 * 1024  # real responses are well under 1 MiB

SEARCH_ENDPOINT = "projects/0.1/projects/active/"
# The multi-project endpoint answers in the same shape as search, so one parser serves both.
PROJECTS_ENDPOINT = "projects/0.1/projects/"
SELF_ENDPOINT = "users/0.1/self/"
# Full description, plus `owner_info` (the client's country and payment status) inside each project.
# Checked against the live API on 2026-09-29: owner_id and the users map come back empty, so
# owner_info is the only place these fields exist.
DETAILS = {"full_description": True, "owner_info": True}

_PROJECT_ID = re.compile(r"[0-9]{1,12}")


class _TimedOut(Exception):
    """One request timed out; `request` decides whether to retry."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Turn a 3xx into HTTPError instead of re-sending the token header to wherever it points."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Client:
    def __init__(
        self,
        token: str,
        tracer: Tracer,
        *,
        opener: Callable[..., Any] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        timeout: float = TIMEOUT_S,
        base_url: str = API_BASE,
    ):
        tracer.add_secret(token)
        check_token(token)
        self._token = token
        self._tracer = tracer
        self._open = opener or urllib.request.build_opener(_NoRedirect()).open
        self._sleep = sleep
        self._timeout = timeout
        self._base_url = base_url.rstrip("/")

    def search_projects(self, query: str, *, limit: int = 20, offset: int = 0) -> list[models.Project]:
        params = {"query": query, "limit": limit, "offset": offset, **DETAILS}
        projects = models.parse_search(self.get(SEARCH_ENDPOINT, params))
        self._tracer.log("result", endpoint=SEARCH_ENDPOINT, count=len(projects))
        return projects

    def get_project(self, project_id: int | str) -> models.Project:
        text = str(project_id)
        if not _PROJECT_ID.fullmatch(text) or int(text) == 0:
            raise self._fail(
                InvalidInputError,
                f"Project id must be a positive number, got {text[:40]!r}.",
                PROJECTS_ENDPOINT,
            )
        wanted = int(text)
        not_found = f"Project {wanted} not found; it may be closed, deleted or private."
        try:
            result = self.get(PROJECTS_ENDPOINT, {"projects[]": [wanted], **DETAILS})
        except NotFoundError:
            raise NotFoundError(not_found) from None
        match = [p for p in models.parse_search(result) if p.id == wanted]
        self._tracer.log("result", endpoint=PROJECTS_ENDPOINT, count=len(match))
        if not match:
            raise self._fail(NotFoundError, not_found, PROJECTS_ENDPOINT)
        return match[0]

    def get_username(self) -> str | None:
        username = models.parse_username(self.get(SELF_ENDPOINT))
        self._tracer.log("result", endpoint=SELF_ENDPOINT, count=int(username is not None))
        return username

    def get(self, endpoint: str, params: dict[str, Any] | None = None) -> Any:
        return self.request("GET", endpoint, params)

    def request(self, method: str, endpoint: str, params: dict[str, Any] | None = None) -> Any:
        """Send one API call; return the `result` part of the JSON envelope."""
        if method != "GET":
            raise self._fail(
                ReadOnlyError,
                f"flx is read-only; refusing to send {method} {endpoint}.",
                endpoint,
                method=method,
            )
        url = self._url(endpoint, params)
        attempt = rate_limited = timeouts = 0
        while True:
            attempt += 1
            try:
                status, headers, body = self._round_trip(url, endpoint, params, attempt)
            except _TimedOut as exc:
                timeouts += 1
                if timeouts > TIMEOUT_RETRIES:
                    raise self._fail(NetworkError, f"Could not reach Freelancer: {exc}.", endpoint) from None
                self._retry(endpoint, attempt, TIMEOUT_WAIT_S, "timeout")
                continue
            if status != 429:
                return self._decode(status, body, endpoint)
            rate_limited += 1
            if rate_limited > len(BACKOFF_S):
                raise self._fail(
                    RateLimitError,
                    f"Freelancer is still rate limiting (HTTP 429) after {len(BACKOFF_S)} retries. "
                    "Wait a minute and try again.",
                    endpoint,
                )
            wait = _retry_wait(rate_limited, headers.get("Retry-After"))
            self._retry(endpoint, attempt, wait, "rate_limit")

    def _retry(self, endpoint: str, attempt: int, wait: float, reason: str) -> None:
        self._tracer.log("retry", endpoint=endpoint, attempt=attempt, wait_s=wait, reason=reason)
        self._sleep(wait)

    def _url(self, endpoint: str, params: dict[str, Any] | None) -> str:
        pairs = {key: _param(value) for key, value in (params or {}).items()}
        query = urllib.parse.urlencode(pairs, doseq=True, quote_via=urllib.parse.quote)
        url = f"{self._base_url}/{endpoint.lstrip('/')}"
        return f"{url}?{query}" if query else url

    def _round_trip(self, url, endpoint, params, attempt) -> tuple[int, Any, bytes]:
        request = urllib.request.Request(
            url,
            headers={
                AUTH_HEADER: self._token,
                "Accept": "application/json",
                "User-Agent": f"flx/{__version__}",
            },
            method="GET",
        )
        started = time.monotonic()
        headers: Any = {}
        try:
            with self._open(request, timeout=self._timeout) as response:
                status, body = response.status, response.read(MAX_BODY_BYTES + 1)
        except urllib.error.HTTPError as exc:
            status, headers, body = exc.code, exc.headers or {}, _read_body(exc)
        except (OSError, http.client.HTTPException) as exc:
            reason = _network_reason(exc, self._timeout)
            self._trace_http(endpoint, params, attempt, started, error=reason)
            if _is_timeout(exc):
                raise _TimedOut(reason) from None
            raise self._fail(NetworkError, f"Could not reach Freelancer: {reason}.", endpoint) from None
        self._trace_http(endpoint, params, attempt, started, status=status)
        return status, headers, body

    def _decode(self, status: int, body: bytes, endpoint: str) -> Any:
        if status == 401:
            raise self._fail(
                AuthError,
                "Freelancer rejected the token (HTTP 401). It is invalid or expired; "
                "put a fresh one in .env.local.",
                endpoint,
            )
        if status == 404:
            raise self._fail(NotFoundError, f"Nothing found at {endpoint} (HTTP 404).", endpoint)
        if 300 <= status < 400:
            raise self._fail(
                ApiError,
                f"Freelancer answered with a redirect (HTTP {status}); flx does not follow "
                "redirects so the token only goes to the API it was meant for.",
                endpoint,
            )
        too_big = len(body) > MAX_BODY_BYTES
        try:
            data = None if too_big else json.loads(body)
        except (ValueError, RecursionError):  # RecursionError: absurdly deep nesting
            data = None
        if status >= 400:
            raise self._fail(ApiError, f"Freelancer returned HTTP {status}{_api_message(data)}.", endpoint)
        if too_big:
            raise self._fail(
                BadResponseError,
                f"Freelancer sent more than {MAX_BODY_BYTES // (1024 * 1024)} MiB; try again later.",
                endpoint,
            )
        if not isinstance(data, dict):
            raise self._fail(
                BadResponseError,
                "Freelancer sent a response that is not the expected JSON; try again later.",
                endpoint,
            )
        if data.get("status") == "error":
            raise self._fail(ApiError, f"Freelancer reported an error{_api_message(data)}.", endpoint)
        return data.get("result")

    def _trace_http(self, endpoint, params, attempt, started, **fields) -> None:
        self._tracer.log(
            "http",
            method="GET",
            endpoint=endpoint,
            params=params or {},
            attempt=attempt,
            duration_ms=round((time.monotonic() - started) * 1000),
            **fields,
        )

    def _fail(self, error_type: type[FlxError], message: str, endpoint: str, **fields) -> FlxError:
        self._tracer.log(
            "error", endpoint=endpoint, error_type=error_type.__name__, error=message, **fields
        )
        return error_type(message)


def _param(value: Any) -> Any:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return [_param(v) for v in value]
    return value


def _retry_wait(attempt: int, retry_after: str | None) -> float:
    """Seconds before retry number `attempt`: Retry-After if usable (capped), else the backoff."""
    try:
        seconds = float(retry_after)  # type: ignore[arg-type]
    except (TypeError, ValueError):  # absent, or the HTTP-date form
        return BACKOFF_S[attempt - 1]
    if not math.isfinite(seconds) or seconds < 0:
        return BACKOFF_S[attempt - 1]
    return min(seconds, MAX_RETRY_AFTER_S)


def _read_body(error: urllib.error.HTTPError) -> bytes:
    try:
        return error.read(MAX_BODY_BYTES + 1) or b""
    except (OSError, http.client.HTTPException, AttributeError):
        return b""


def _is_timeout(exc: BaseException) -> bool:
    reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
    return isinstance(reason, TimeoutError)


def _network_reason(exc: BaseException, timeout: float) -> str:
    if _is_timeout(exc):
        return f"timed out after {timeout} s"
    reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
    return str(reason) or type(reason).__name__


def _api_message(data: Any) -> str:
    message = data.get("message") if isinstance(data, dict) else None
    return f": {message[:200]}" if isinstance(message, str) and message else ""
