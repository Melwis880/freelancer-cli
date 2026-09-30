"""One test class per scenario in tests/SCENARIOS.md. Only S19 opens a socket, on 127.0.0.1."""

import contextlib
import http.server
import io
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
from pathlib import Path
from unittest import mock

import _path  # noqa: F401
from fakes import (
    SEARCH_RESULT,
    TOKEN,
    FakeOpener,
    FakeResponse,
    http_error,
    make_client,
    make_tracer,
    ok,
    read_trace,
    run_cli,
    trace_lines,
    trace_text,
)

from flx import auth, cli, client as client_module, models
from flx.client import AUTH_HEADER, Client
from flx.errors import (
    ApiError,
    AuthError,
    BadResponseError,
    InvalidInputError,
    NetworkError,
    NotFoundError,
    RateLimitError,
    ReadOnlyError,
    TokenError,
)
from flx.trace import Tracer


def query_of(request):
    return urllib.parse.parse_qs(urllib.parse.urlsplit(request.full_url).query)


def project(id, time_submitted):
    return models.Project(
        id, f"p{id}", None, None, None, None, None, None, None, time_submitted, None, None, None, None
    )


class S01NormalSearch(unittest.TestCase):
    def test_search_returns_parsed_projects(self):
        rig = make_client(self, ok(SEARCH_RESULT))
        projects = rig.client.search_projects("n8n")
        self.assertEqual(
            projects[0],
            models.Project(
                id=101,
                title="Build an n8n workflow",
                url="https://www.freelancer.com/projects/n8n/build-an-n8n-workflow",
                type="fixed",
                budget_min=30.0,
                budget_max=250.0,
                currency="USD",
                bid_count=12,
                bid_avg=140.5,
                time_submitted=1790000000,
                client_country="Germany",
                payment_verified=True,
                description="Connect a CRM to Slack with n8n.",
                skills=("n8n", "Zapier"),  # a job without a name is skipped
            ),
        )
        self.assertIsNone(projects[1].skills)  # no `jobs` sent
        self.assertEqual(projects[1].client_country, "Canada")
        self.assertIs(projects[1].payment_verified, False)
        self.assertEqual(projects[1].description, "Scrape product pages.")  # preview as fallback

    def test_request_is_an_authenticated_get_to_the_search_endpoint(self):
        rig = make_client(self, ok(SEARCH_RESULT))
        rig.client.search_projects("n8n", limit=5, offset=10)
        (request,) = rig.opener.requests
        self.assertEqual(request.get_method(), "GET")
        self.assertIsNone(request.data)
        self.assertEqual(request.get_header(AUTH_HEADER.capitalize()), TOKEN)
        self.assertEqual(
            urllib.parse.urlsplit(request.full_url).path, "/api/projects/0.1/projects/active/"
        )
        query = query_of(request)
        self.assertEqual(query["query"], ["n8n"])
        self.assertEqual(query["limit"], ["5"])
        self.assertEqual(query["offset"], ["10"])
        self.assertEqual(query["full_description"], ["true"])
        self.assertEqual(query["owner_info"], ["true"])  # the only source of client country/payment
        self.assertEqual(query["job_details"], ["true"])  # skill names


class S02EmptyResult(unittest.TestCase):
    def test_no_projects_gives_an_empty_list(self):
        rig = make_client(self, ok({"projects": [], "total_count": 0}))
        self.assertEqual(rig.client.search_projects("nothing-matches-this"), [])
        self.assertEqual(read_trace(rig.tracer)[-1]["count"], 0)

    def test_missing_result_or_projects_key_gives_an_empty_list(self):
        rig = make_client(self, ok({}), FakeResponse({"status": "success"}))
        self.assertEqual(rig.client.search_projects("a"), [])
        self.assertEqual(rig.client.search_projects("b"), [])


class S03MissingToken(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name) / "cwd"
        self.config = Path(tmp.name) / "config"
        self.base.mkdir()
        self.config.mkdir()

    def write_env_file(self, text, where=None):
        ((where or self.base) / auth.ENV_FILE).write_text(text, encoding="utf-8")

    def load(self, environ):
        return auth.load_token(self.base, self.config, environ=environ)

    def test_no_token_anywhere_gives_a_clear_message(self):
        with self.assertRaises(TokenError) as ctx:
            self.load({})
        self.assertIn("FREELANCER_TOKEN", str(ctx.exception))
        self.assertIn(".env.local", str(ctx.exception))

    def test_empty_token_is_refused_before_any_request(self):
        opener = FakeOpener(ok(SEARCH_RESULT))
        with self.assertRaises(TokenError):
            Client("", make_tracer(self), opener=opener)
        self.assertEqual(opener.requests, [])

    def test_one_wording_for_a_missing_token(self):
        with self.assertRaises(TokenError) as loaded:
            self.load({})
        with self.assertRaises(TokenError) as checked:
            auth.check_token("")
        prefix = "No Freelancer token found. Set FREELANCER_TOKEN, or put FREELANCER_TOKEN=... in "
        self.assertTrue(str(loaded.exception).startswith(prefix))
        self.assertTrue(str(checked.exception).startswith(prefix))
        self.assertIn(str(self.config), str(loaded.exception))

    def test_env_file_is_the_fallback(self):
        self.write_env_file('# local secrets\nexport FREELANCER_TOKEN="from-file"\nOTHER=x\n')
        self.assertEqual(self.load({}), "from-file")

    def test_env_var_wins_over_env_file(self):
        self.write_env_file("FREELANCER_TOKEN=from-file\n")
        self.assertEqual(self.load({"FREELANCER_TOKEN": "from-env"}), "from-env")

    def test_blank_env_var_falls_back_to_env_file(self):
        self.write_env_file("FREELANCER_TOKEN='from-file'\n")
        self.assertEqual(self.load({"FREELANCER_TOKEN": "  "}), "from-file")

    def test_config_dir_file_is_the_last_fallback(self):
        self.write_env_file("FREELANCER_TOKEN=from-config\n", where=self.config)
        self.assertEqual(self.load({}), "from-config")

    def test_cwd_file_overrides_config_dir_file(self):
        self.write_env_file("FREELANCER_TOKEN=from-config\n", where=self.config)
        self.write_env_file("FREELANCER_TOKEN=from-cwd\n")
        self.assertEqual(self.load({}), "from-cwd")


class S04Unauthorized(unittest.TestCase):
    def test_401_is_a_clear_auth_error_without_retry(self):
        rig = make_client(self, http_error(401, {"status": "error", "message": "You must be logged in"}))
        with self.assertRaises(AuthError) as ctx:
            rig.client.search_projects("n8n")
        self.assertIn("401", str(ctx.exception))
        self.assertIn("expired", str(ctx.exception))
        self.assertNotIn(TOKEN, str(ctx.exception))
        self.assertEqual(len(rig.opener.requests), 1)
        self.assertEqual(rig.sleeps, [])


class S05RateLimit(unittest.TestCase):
    def test_gives_up_after_three_retries_with_backoff(self):
        rig = make_client(self, *[http_error(429) for _ in range(4)])
        with self.assertRaises(RateLimitError) as ctx:
            rig.client.search_projects("n8n")
        self.assertEqual(rig.sleeps, [1, 2, 4])
        self.assertEqual(len(rig.opener.requests), 4)
        self.assertIn("Wait a minute", str(ctx.exception))

    def test_recovers_when_a_retry_succeeds(self):
        rig = make_client(self, http_error(429), ok(SEARCH_RESULT))
        self.assertEqual(len(rig.client.search_projects("n8n")), 2)
        self.assertEqual(rig.sleeps, [1])

    def test_honours_retry_after_up_to_ten_seconds(self):
        cases = {"3": 3, "60": 10, "0": 0, "soon": 1, "Wed, 21 Oct 2026 07:28:00 GMT": 1, "-5": 1, "nan": 1}
        for header, expected in cases.items():
            with self.subTest(retry_after=header):
                rig = make_client(self, http_error(429, headers={"Retry-After": header}), ok(SEARCH_RESULT))
                rig.client.search_projects("n8n")
                self.assertEqual(rig.sleeps, [expected])

    def test_other_errors_are_not_retried(self):
        rig = make_client(self, http_error(500))
        with self.assertRaises(ApiError):
            rig.client.search_projects("n8n")
        self.assertEqual(rig.sleeps, [])


class S06NetworkError(unittest.TestCase):
    def test_connection_problems_become_network_errors(self):
        failures = [
            urllib.error.URLError(OSError("Name or service not known")),
            ConnectionResetError("connection reset by peer"),
        ]
        for failure in failures:
            with self.subTest(failure=failure):
                rig = make_client(self, failure)
                with self.assertRaises(NetworkError) as ctx:
                    rig.client.search_projects("n8n")
                self.assertIn("Could not reach Freelancer", str(ctx.exception))
                self.assertEqual(len(rig.opener.requests), 1)

    def test_timeout_is_retried_once_then_says_it_timed_out(self):
        for failure in (TimeoutError("timed out"), urllib.error.URLError(TimeoutError())):
            with self.subTest(failure=failure):
                rig = make_client(self, failure, failure)
                with self.assertRaises(NetworkError) as ctx:
                    rig.client.search_projects("n8n")
                self.assertIn("timed out after 20 s", str(ctx.exception))
                self.assertEqual(len(rig.opener.requests), 2)
                self.assertEqual(rig.sleeps, [2])

    def test_timeout_then_success_recovers(self):
        rig = make_client(self, TimeoutError("timed out"), ok(SEARCH_RESULT))
        self.assertEqual(len(rig.client.search_projects("n8n")), 2)
        lines = read_trace(rig.tracer)
        self.assertEqual([l["step"] for l in lines], ["http", "retry", "http", "result"])
        self.assertEqual((lines[1]["reason"], lines[1]["wait_s"]), ("timeout", 2))
        self.assertEqual(lines[0]["error"], "timed out after 20 s")


class S07BadData(unittest.TestCase):
    def test_body_that_is_not_json_is_a_clear_error(self):
        for body in (b"<html>maintenance</html>", b"", b"\xff\xfe\x00", b"[1, 2]", b'"text"'):
            with self.subTest(body=body):
                rig = make_client(self, FakeResponse(body))
                with self.assertRaises(BadResponseError):
                    rig.client.search_projects("n8n")

    def test_missing_fields_come_back_empty(self):
        rig = make_client(self, ok({"projects": [{"id": 5}]}))
        (only,) = rig.client.search_projects("n8n")
        self.assertEqual(only, models.Project(5, *[None] * 13))

    def test_wrong_types_come_back_empty(self):
        raw = {
            "id": "not-a-number",
            "owner_info": {"country": "Germany", "status": None},
            "title": 42,
            "budget": "cheap",
            "currency": None,
            "bid_stats": {"bid_count": True, "bid_avg": "high"},
            "time_submitted": "yesterday",
        }
        rig = make_client(self, ok({"projects": [raw, "junk", None]}))
        (only,) = rig.client.search_projects("n8n")
        self.assertEqual(only, models.Project(*[None] * 14))


class S08ReadOnly(unittest.TestCase):
    def test_every_method_but_get_is_refused_before_sending(self):
        for method in ("POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "get"):
            with self.subTest(method=method):
                rig = make_client(self, ok({}))
                with self.assertRaises(ReadOnlyError):
                    rig.client.request(method, "projects/0.1/bids/")
                self.assertEqual(rig.opener.requests, [])
                self.assertEqual(read_trace(rig.tracer)[-1]["error_type"], "ReadOnlyError")

    def test_client_has_no_write_helpers(self):
        public = {name.lower() for name in dir(Client) if not name.startswith("_")}
        for word in ("post", "put", "patch", "delete", "bid", "message", "send"):
            self.assertFalse([n for n in public if word in n], f"unexpected '{word}' method")


class S09ProjectId(unittest.TestCase):
    def test_non_numeric_id_is_refused_before_sending(self):
        for bad in ("abc", "12a", "-5", "1.5", "", " 12", "0", "١٢", "²", "9" * 13, True):
            with self.subTest(project_id=bad):
                rig = make_client(self, ok({}))
                with self.assertRaises(InvalidInputError):
                    rig.client.get_project(bad)
                self.assertEqual(rig.opener.requests, [])

    def test_numeric_id_reaches_the_projects_endpoint(self):
        for good in ("123", 123):
            with self.subTest(project_id=good):
                rig = make_client(self, ok({"projects": [{"id": 123, "title": "Chatbot"}]}))
                self.assertEqual(rig.client.get_project(good).title, "Chatbot")
                (request,) = rig.opener.requests
                self.assertEqual(urllib.parse.urlsplit(request.full_url).path, "/api/projects/0.1/projects/")
                self.assertEqual(query_of(request)["projects[]"], ["123"])


class S10QueryEncoding(unittest.TestCase):
    def test_special_characters_are_encoded(self):
        rig = make_client(self, ok(SEARCH_RESULT))
        rig.client.search_projects("c++ & n8n")
        (request,) = rig.opener.requests
        self.assertIn("query=c%2B%2B%20%26%20n8n", request.full_url)
        self.assertEqual(query_of(request)["query"], ["c++ & n8n"])

    def test_query_cannot_inject_parameters(self):
        text = "a&limit=999#frag?x=/y ğüşİ"
        rig = make_client(self, ok(SEARCH_RESULT))
        rig.client.search_projects(text, limit=5)
        (request,) = rig.opener.requests
        self.assertEqual(query_of(request)["query"], [text])
        self.assertEqual(query_of(request)["limit"], ["5"])
        self.assertNotIn("#", request.full_url)


class S11ScanDedup(unittest.TestCase):
    def test_same_project_from_two_keywords_appears_once(self):
        by_n8n = [project(101, 100), project(102, 300)]
        by_zapier = [project(102, 300), project(103, 200)]
        merged = models.merge_projects([by_n8n, by_zapier])
        self.assertEqual([p.id for p in merged], [102, 103, 101])  # newest first

    def test_undated_projects_go_last_and_nothing_is_dropped(self):
        merged = models.merge_projects([[project(1, None), project(None, 50)], [project(None, 60)]])
        self.assertEqual([p.id for p in merged], [None, None, 1])
        self.assertEqual(merged[-1].time_submitted, None)


class S12TraceHasNoToken(unittest.TestCase):
    def test_token_never_reaches_trace_or_debug_output(self):
        stream = io.StringIO()
        rig = make_client(
            self,
            ok(SEARCH_RESULT),
            http_error(401),
            http_error(429, headers={"Retry-After": "1"}),
            http_error(500, {"message": f"echoed {TOKEN}"}),
            urllib.error.URLError(f"proxy said {TOKEN}"),
            stream=stream,
        )
        rig.client.search_projects("n8n")
        for _ in range(3):
            with contextlib.suppress(AuthError, ApiError, NetworkError):
                rig.client.search_projects("n8n")
        rig.tracer.log("note", leaked=f"Bearer {TOKEN}", nested={"deep": [TOKEN]})

        written = trace_text(rig.tracer)
        self.assertGreater(len(written.splitlines()), 8)
        self.assertNotIn(TOKEN, written)
        self.assertNotIn(TOKEN, stream.getvalue())
        self.assertIn("Bearer ***", written)

    def test_long_values_are_shortened(self):
        tracer = make_tracer(self)
        tracer.log("note", description="x" * 5000)
        self.assertLess(len(read_trace(tracer)[0]["description"]), 300)


class S14NotFound(unittest.TestCase):
    def test_unknown_project_gives_a_clear_message(self):
        outcomes = {
            "http 404": http_error(404, {"status": "error", "message": "Project not found"}),
            "empty list": ok({"projects": []}),
            "other project": ok({"projects": [{"id": 5}]}),
        }
        for label, outcome in outcomes.items():
            with self.subTest(label):
                rig = make_client(self, outcome)
                with self.assertRaises(NotFoundError) as ctx:
                    rig.client.get_project(999)
                self.assertIn("Project 999 not found", str(ctx.exception))
                self.assertEqual(rig.sleeps, [])


class S15DebugMirror(unittest.TestCase):
    def test_debug_prints_the_same_lines_as_the_trace_file(self):
        run = run_cli(self, ["--debug", "whoami"], ok({"username": "meric"}))
        mirrored = [line for line in run.err.splitlines() if line.startswith("{")]
        self.assertEqual(mirrored, trace_lines(run.config))
        self.assertEqual(
            [json.loads(line)["step"] for line in mirrored], ["start", "http", "result", "end"]
        )

    def test_without_debug_stderr_has_no_trace_lines(self):
        run = run_cli(self, ["whoami"], ok({"username": "meric"}))
        self.assertEqual(run.err, "")
        self.assertTrue(trace_lines(run.config))  # still traced to disk

    def test_cli_error_message_is_masked(self):
        run = run_cli(self, ["--debug", "whoami"], http_error(500, {"message": f"server echoed {TOKEN}"}))
        self.assertEqual(run.code, cli.EXIT_ERROR)
        self.assertIn("flx: Freelancer returned HTTP 500: server echoed ***.", run.err)
        self.assertNotIn(TOKEN, run.err)


class S16TraceSteps(unittest.TestCase):
    def test_one_run_is_linked_by_run_id_and_seq(self):
        rig = make_client(self, http_error(429), ok(SEARCH_RESULT))
        rig.client.search_projects("n8n")
        lines = read_trace(rig.tracer)
        self.assertEqual([l["step"] for l in lines], ["http", "retry", "http", "result"])
        self.assertEqual([l["seq"] for l in lines], [1, 2, 3, 4])
        self.assertEqual({l["run_id"] for l in lines}, {rig.tracer.run_id})
        self.assertEqual([l["status"] for l in lines if l["step"] == "http"], [429, 200])
        self.assertEqual((lines[1]["wait_s"], lines[1]["reason"]), (1, "rate_limit"))
        self.assertEqual(lines[3]["count"], 2)
        for line in lines:
            self.assertEqual(line["command"], "test")
            self.assertIn("ts", line)
            self.assertEqual(line["endpoint"], "projects/0.1/projects/active/")
        self.assertIsInstance(lines[0]["duration_ms"], int)
        self.assertEqual(lines[0]["params"]["query"], "n8n")

    def test_failure_ends_with_an_error_step(self):
        rig = make_client(self, http_error(401))
        with self.assertRaises(AuthError):
            rig.client.search_projects("n8n")
        self.assertEqual([l["step"] for l in read_trace(rig.tracer)], ["http", "error"])

    def test_cli_run_has_start_and_end(self):
        run = run_cli(self, ["search", "n8n", "--limit", "5"], ok(SEARCH_RESULT))
        lines = [json.loads(line) for line in trace_lines(run.config)]
        self.assertEqual([l["step"] for l in lines], ["start", "http", "result", "end"])
        self.assertEqual(len({l["run_id"] for l in lines}), 1)
        self.assertEqual(lines[0]["options"]["query"], "n8n")
        self.assertEqual(lines[-1]["exit_code"], 0)


class S17MalformedToken(unittest.TestCase):
    def test_token_that_would_break_the_header_is_refused_without_echo(self):
        for bad in ("abc def", "abc\ndef", "abc\r\nX-Evil: 1", "tökén", "abc\t"):
            with self.subTest(token=bad):
                opener = FakeOpener(ok({}))
                with self.assertRaises(TokenError) as ctx:
                    Client(bad, make_tracer(self), opener=opener)
                self.assertNotIn(bad, str(ctx.exception))
                self.assertEqual(opener.requests, [])


class S18OtherApiErrors(unittest.TestCase):
    def test_error_status_shows_code_and_api_message(self):
        rig = make_client(self, http_error(503, {"status": "error", "message": "Down for maintenance"}))
        with self.assertRaises(ApiError) as ctx:
            rig.client.search_projects("n8n")
        self.assertEqual(str(ctx.exception), "Freelancer returned HTTP 503: Down for maintenance.")

    def test_error_envelope_with_200_is_an_error(self):
        rig = make_client(self, FakeResponse({"status": "error", "message": "Invalid query"}))
        with self.assertRaises(ApiError) as ctx:
            rig.client.search_projects("n8n")
        self.assertIn("Invalid query", str(ctx.exception))


class S33HostileResponse(unittest.TestCase):
    def test_oversized_body_is_a_clear_error_and_is_not_read_in_full(self):
        body = json.dumps({"status": "success", "result": {"projects": []}, "pad": "x" * 200}).encode()
        response = FakeResponse(body)
        with mock.patch.object(client_module, "MAX_BODY_BYTES", 100):
            rig = make_client(self, response)
            with self.assertRaises(BadResponseError) as ctx:
                rig.client.search_projects("n8n")
        self.assertIn("more than", str(ctx.exception))
        self.assertEqual(response.read_size, 101)

    def test_deeply_nested_json_is_a_clear_error(self):
        rig = make_client(self, FakeResponse(b"[" * 100_000 + b"]" * 100_000))
        with self.assertRaises(BadResponseError):
            rig.client.search_projects("n8n")


class _RecordingHandler(http.server.BaseHTTPRequestHandler):
    seen = []

    def do_GET(self):
        self.seen.append((self.command, self.path, self.headers.get(AUTH_HEADER)))
        if self.path.startswith("/api/moved"):
            self.send_response(302)
            self.send_header("Location", "/elsewhere/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = json.dumps({"status": "success", "result": {"projects": []}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class S19NoRedirects(unittest.TestCase):
    """Real urllib transport against a throwaway local server."""

    def setUp(self):
        _RecordingHandler.seen = []
        server = http.server.HTTPServer(("127.0.0.1", 0), _RecordingHandler)
        # A short poll interval lets shutdown() return at once instead of after up to 0.5 s.
        threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        patcher = mock.patch.dict(os.environ, {"no_proxy": "*", "NO_PROXY": "*"})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = Client(
            TOKEN, make_tracer(self), base_url=f"http://127.0.0.1:{server.server_port}/api", timeout=5
        )

    def test_redirect_is_not_followed(self):
        with self.assertRaises(ApiError) as ctx:
            self.client.get("moved/")
        self.assertIn("redirect", str(ctx.exception))
        self.assertEqual([path for _, path, _ in _RecordingHandler.seen], ["/api/moved/"])

    def test_wire_request_is_a_get_with_the_token_header(self):
        self.assertEqual(self.client.search_projects("c++ & n8n"), [])
        ((method, path, token),) = _RecordingHandler.seen
        self.assertEqual(method, "GET")
        self.assertEqual(token, TOKEN)
        self.assertIn("query=c%2B%2B%20%26%20n8n", path)


class S20TraceUnwritable(unittest.TestCase):
    def test_command_keeps_going_with_one_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            blocker = Path(tmp) / "traces"
            blocker.write_text("not a directory")
            err = io.StringIO()
            tracer = Tracer("test", blocker, stream=err)
            tracer.log("one")
            tracer.log("two")
        warnings = [line for line in err.getvalue().splitlines() if "could not write trace" in line]
        self.assertEqual(len(warnings), 1)


if __name__ == "__main__":
    unittest.main()
