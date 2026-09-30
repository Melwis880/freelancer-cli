"""Command scenarios from tests/SCENARIOS.md (S13, S21 onward, plus S3 at CLI level).

Every test runs the real CLI in-process against a fake API and a temp base dir; nothing touches the
network, the real environment or the repo's own .env.local.
"""

import copy
import dataclasses
import json
import os
import stat
import threading
import unicodedata
import unittest
import urllib.error
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import _path  # noqa: F401
from fakes import (
    NOW,
    SEARCH_RESULT,
    TOKEN,
    FakeResponse,
    http_error,
    make_client,
    ok,
    run_cli,
    temp_dir,
    trace_lines,
)

from flx import SCHEMA_VERSION, cli, files, models, render
from flx.errors import InvalidInputError

PROJECT_FIELDS = [
    "id",
    "title",
    "url",
    "type",
    "budget_min",
    "budget_max",
    "currency",
    "bid_count",
    "bid_avg",
    "time_submitted",
    "client_country",
    "payment_verified",
    "description",
    "skills",
]


def query_of(request):
    return urllib.parse.parse_qs(urllib.parse.urlsplit(request.full_url).query)


def result_with(*projects):
    return {"projects": list(projects)}


def screen_width(text):
    """Columns the text takes on a terminal, measured independently of render.display_width."""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)


class S03NoTokenCli(unittest.TestCase):
    def test_every_command_needs_a_token_before_any_request(self):
        for argv in (["whoami"], ["search", "n8n"], ["project", "1"], ["scan", "--only-new"]):
            with self.subTest(argv=argv):
                run = run_cli(self, argv, token=None, keywords="n8n\n")
                self.assertEqual(run.code, cli.EXIT_ERROR)
                self.assertIn("FREELANCER_TOKEN", run.err)
                self.assertEqual(run.opener.requests, [])
                self.assertEqual(run.out, "")


class S13OnlyNew(unittest.TestCase):
    def test_second_scan_does_not_repeat_projects(self):
        first = run_cli(self, ["scan", "--only-new"], ok(SEARCH_RESULT), keywords="n8n\n")
        self.assertIn("Build an n8n workflow", first.out)
        second = run_cli(self, ["scan", "--only-new"], ok(SEARCH_RESULT), root=first.root)
        self.assertEqual(second.out, "No new projects.\n")
        self.assertEqual(second.code, 0)

    def test_only_projects_not_seen_before_are_shown(self):
        first = run_cli(self, ["scan", "--only-new"], ok(SEARCH_RESULT), keywords="n8n\n")
        later = result_with({"id": 102, "title": "Python scraper"}, {"id": 103, "title": "Zapier bot"})
        second = run_cli(self, ["scan", "--only-new", "--json"], ok(later), root=first.root)
        self.assertEqual([p["id"] for p in json.loads(second.out)["projects"]], [103])

    def test_state_file_holds_project_ids_only(self):
        run = run_cli(self, ["scan", "--only-new"], ok(SEARCH_RESULT), keywords="n8n\n")
        state = json.loads((run.config / files.SEEN_FILE).read_text(encoding="utf-8"))
        self.assertEqual(state, {"seen": [102, 101]})

    def test_plain_scan_leaves_state_alone(self):
        run = run_cli(self, ["scan"], ok(SEARCH_RESULT), keywords="n8n\n")
        self.assertFalse((run.config / files.SEEN_FILE).exists())

    def test_failed_scan_does_not_mark_anything_seen(self):
        run = run_cli(
            self, ["scan", "--only-new"], ok(SEARCH_RESULT), http_error(401), keywords="n8n\nzapier\n"
        )
        self.assertEqual(run.code, cli.EXIT_ERROR)
        self.assertEqual(run.out, "")
        self.assertFalse((run.config / files.SEEN_FILE).exists())


class S21Whoami(unittest.TestCase):
    def test_prints_the_username_and_nothing_else(self):
        profile = {"id": 1, "username": "meric", "email": "meric@example.com", "display_name": "Meriç"}
        run = run_cli(self, ["whoami"], ok(profile))
        self.assertEqual(run.code, 0)
        self.assertEqual(run.out, "Token works. Logged in as meric.\n")
        (request,) = run.opener.requests
        self.assertEqual(urllib.parse.urlsplit(request.full_url).path, "/api/users/0.1/self/")
        self.assertNotIn(TOKEN, run.out + run.err)

    def test_missing_username_is_an_error(self):
        run = run_cli(self, ["whoami"], ok({}))
        self.assertEqual(run.code, cli.EXIT_ERROR)
        self.assertIn("did not return a username", run.err)


class S22Table(unittest.TestCase):
    def setUp(self):
        self.titles = ["A" * 300, "日本語のチャットボットを作ってください。長いタイトルです", "Build an n8n workflow"]
        raw = copy.deepcopy(SEARCH_RESULT)
        raw["projects"] = [
            {**raw["projects"][0], "id": 1, "title": self.titles[0]},
            {**raw["projects"][1], "id": 22222222, "title": self.titles[1]},
            {**raw["projects"][0], "id": 333, "title": self.titles[2]},
        ]
        self.result = raw

    def test_rows_fit_the_terminal_and_titles_line_up(self):
        for columns in (80, 100, 160):
            with self.subTest(columns=columns):
                lines = run_cli(self, ["search", "n8n"], ok(self.result), columns=columns).out.splitlines()
                self.assertEqual(len(lines), 4)
                for line in lines:
                    self.assertLessEqual(screen_width(line), columns, line)
                title_start = {screen_width(lines[0][: lines[0].index("TITLE")])}
                for line, title in zip(lines[1:], self.titles):
                    title_start.add(screen_width(line[: line.index(title[:2])]))
                self.assertEqual(len(title_start), 1, lines)
                self.assertTrue(lines[1].endswith(render.ELLIPSIS))

    def test_row_shows_the_listing_fields(self):
        out = run_cli(self, ["search", "n8n"], ok(SEARCH_RESULT)).out
        header, first, second = out.splitlines()
        self.assertEqual(header.split(), ["ID", "AGE", "BUDGET", "BIDS", "AVG", "COUNTRY", "VERIFIED", "TITLE"])
        self.assertEqual(first.split()[:8], ["101", "2h", "30-250", "USD", "12", "140", "Germany", "yes"])
        self.assertIn("15-25 EUR/h", second)  # hourly shows as /h
        self.assertIn(" no ", second)

    def test_narrow_terminal_hides_the_least_useful_columns_first(self):
        raw = copy.deepcopy(SEARCH_RESULT)
        raw["projects"][0].update(id=39876543, budget={"minimum": 1500, "maximum": 3000})
        raw["projects"][0]["owner_info"]["country"]["name"] = "United Kingdom"
        expected = {
            120: ["ID", "AGE", "BUDGET", "BIDS", "AVG", "COUNTRY", "VERIFIED", "TITLE"],
            80: ["ID", "AGE", "BUDGET", "BIDS", "VERIFIED", "TITLE"],
            60: ["ID", "AGE", "BUDGET", "TITLE"],
        }
        for columns, headers in expected.items():
            with self.subTest(columns=columns):
                lines = run_cli(self, ["search", "n8n"], ok(raw), columns=columns).out.splitlines()
                self.assertEqual(lines[0].split(), headers)
                for line in lines:
                    self.assertLessEqual(screen_width(line), columns, line)
                title = lines[0].index("TITLE")
                self.assertGreaterEqual(columns - title, render.MIN_TITLE)

    def test_empty_result_says_so(self):
        run = run_cli(self, ["search", "nothing"], ok(result_with()))
        self.assertEqual(run.out, "No projects found.\n")


class S23Json(unittest.TestCase):
    def test_search_json_carries_schema_version_and_every_field(self):
        data = json.loads(run_cli(self, ["search", "n8n", "--json"], ok(SEARCH_RESULT)).out)
        self.assertEqual(data["schema_version"], SCHEMA_VERSION)
        self.assertEqual(data["command"], "search")
        self.assertEqual((data["query"], data["limit"], data["offset"], data["count"]), ("n8n", 20, 0, 2))
        self.assertEqual(data["generated_at"], render.iso_utc(NOW))
        first = data["projects"][0]
        self.assertEqual(list(first), PROJECT_FIELDS)
        posted = datetime.fromtimestamp(1790000000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.assertEqual(first["time_submitted"], posted)
        self.assertEqual(first["description"], "Connect a CRM to Slack with n8n.")
        self.assertIs(first["payment_verified"], True)

    def test_field_list_is_pinned_to_the_schema_version(self):
        # Changing a field? Bump SCHEMA_VERSION in src/flx/__init__.py and update both lines here.
        self.assertEqual(SCHEMA_VERSION, 3)
        self.assertEqual([f.name for f in dataclasses.fields(models.Project)], PROJECT_FIELDS)

    def test_project_and_scan_json(self):
        project = json.loads(run_cli(self, ["project", "101", "--json"], ok(SEARCH_RESULT)).out)
        self.assertEqual((project["schema_version"], project["command"]), (SCHEMA_VERSION, "project"))
        self.assertEqual(list(project["project"]), PROJECT_FIELDS)
        self.assertEqual(project["project"]["client_country"], "Germany")

        scan = json.loads(run_cli(self, ["scan", "--json"], ok(SEARCH_RESULT), keywords="n8n\n").out)
        self.assertEqual(scan["keywords"], ["n8n"])
        self.assertEqual(scan["failed_keywords"], [])
        self.assertEqual((scan["skills"], scan["failed_skills"]), ([], []))
        self.assertEqual(project["project"]["skills"], ["n8n", "Zapier"])
        self.assertIs(scan["only_new"], False)
        self.assertEqual([p["id"] for p in scan["projects"]], [102, 101])


class S24ProjectDetail(unittest.TestCase):
    def test_detail_shows_description_budget_bids_and_client(self):
        run = run_cli(self, ["project", "101"], ok(SEARCH_RESULT))
        self.assertEqual(run.code, 0)
        for expected in (
            "Build an n8n workflow",
            "https://www.freelancer.com/projects/n8n/build-an-n8n-workflow",
            "30-250 USD",
            "12 (average 140.50 USD)",
            "(2h ago)",
            "Germany, payment verified",
            "Skills  n8n, Zapier",
            "Connect a CRM to Slack with n8n.",
        ):
            self.assertIn(expected, run.out)
        (request,) = run.opener.requests
        self.assertEqual(query_of(request)["projects[]"], ["101"])
        self.assertEqual(query_of(request)["owner_info"], ["true"])

    def test_missing_fields_do_not_break_the_view(self):
        run = run_cli(self, ["project", "5"], ok(result_with({"id": 5})))
        self.assertEqual(run.code, 0)
        self.assertIn("(no title)", run.out)
        self.assertIn("country unknown, payment status unknown", run.out)

    def test_bad_id_fails_before_any_request(self):
        run = run_cli(self, ["project", "12a"])
        self.assertEqual(run.code, cli.EXIT_ERROR)
        self.assertIn("positive number", run.err)
        self.assertEqual(run.opener.requests, [])


class S25Scan(unittest.TestCase):
    def test_every_keyword_is_searched_with_a_pause_between(self):
        keywords = "# my terms\n\nn8n\nZapier\nzapier\n  llm  \n"
        second = result_with(
            {"id": 102, "title": "Python scraper", "time_submitted": 1790000500},
            {"id": 103, "title": "Zapier bot", "time_submitted": 1790000900},
        )
        run = run_cli(
            self, ["scan", "--json"], ok(SEARCH_RESULT), ok(second), ok(result_with()), keywords=keywords
        )
        self.assertEqual(run.code, 0)
        queries = [query_of(r) for r in run.opener.requests]
        self.assertEqual([q["query"][0] for q in queries], ["n8n", "Zapier", "llm"])
        self.assertEqual({q["limit"][0] for q in queries}, {"20"})
        self.assertEqual(run.sleeps, [1, 1])
        data = json.loads(run.out)
        self.assertEqual(data["keywords"], ["n8n", "Zapier", "llm"])
        self.assertEqual([p["id"] for p in data["projects"]], [103, 102, 101])

    def test_pause_counts_from_the_start_of_the_previous_request(self):
        outcomes = [ok(result_with()) for _ in range(3)]
        slow = run_cli(self, ["scan"], *outcomes, keywords="a\nb\nc\n", request_s=1.4)
        self.assertEqual(slow.sleeps, [])  # each request already took longer than the gap
        outcomes = [ok(result_with()) for _ in range(3)]
        quick = run_cli(self, ["scan"], *outcomes, keywords="a\nb\nc\n", request_s=0.3)
        self.assertEqual(len(quick.sleeps), 2)
        for wait in quick.sleeps:
            self.assertAlmostEqual(wait, 0.7)


class S26Keywords(unittest.TestCase):
    def test_default_keywords_are_single_terms(self):
        # the API matches multi-word terms loosely and fills the results with unrelated jobs
        for keyword in files.DEFAULT_KEYWORDS:
            self.assertEqual(keyword.split(), [keyword])

    def test_empty_keywords_file_stops_before_any_request(self):
        for content in ("", "# only a comment\n\n   \n"):
            with self.subTest(content=content):
                run = run_cli(self, ["scan"], keywords=content)
                self.assertEqual(run.code, cli.EXIT_ERROR)
                self.assertIn("keywords", run.err)
                self.assertEqual(run.opener.requests, [])


class S27TerminalSafety(unittest.TestCase):
    EVIL = {
        "id": 7,
        "title": "Nice job\x1b[2J\x1b]0;pwned\x07 ‮exe.txt\ud800",
        "type": "fixed\x1b[31m",
        "currency": {"code": "US\x1bD"},
        "description": "line one\x1b[31m red\r\nline two​\x00 line three",
    }
    UNSAFE = ("\x1b", "\x07", "\x00", "‮", "​", " ", "\ud800", "\r")

    def test_escape_sequences_never_reach_the_terminal(self):
        for argv in (["search", "x"], ["project", "7"]):
            with self.subTest(argv=argv):
                run = run_cli(self, argv, ok(result_with(self.EVIL)))
                self.assertEqual(run.code, 0)
                for char in self.UNSAFE:
                    self.assertNotIn(char, run.out)
        detail = run_cli(self, ["project", "7"], ok(result_with(self.EVIL))).out
        self.assertIn("line one", detail)
        self.assertIn("line two", detail)
        self.assertIn("line three", detail)

    def test_json_escapes_but_keeps_the_original_text(self):
        run = run_cli(self, ["search", "x", "--json"], ok(result_with(self.EVIL)))
        for char in self.UNSAFE:
            self.assertNotIn(char, run.out)
        self.assertEqual(json.loads(run.out)["projects"][0]["title"], self.EVIL["title"])

    def test_error_messages_are_cleaned(self):
        run = run_cli(self, ["search", "x"], http_error(500, {"message": "bad\x1b[2Jthing"}))
        self.assertNotIn("\x1b", run.err)
        self.assertIn("bad [2Jthing", run.err)

    def test_scan_warnings_are_cleaned(self):
        evil = http_error(500, {"message": "bad\x1b]52;c;cHduZWQ=\x07thing\u202e"})
        run = run_cli(self, ["scan"], evil, ok(SEARCH_RESULT), keywords="n8n\nzapier\n")
        self.assertEqual(run.code, 0)
        self.assertIn("keyword 'n8n' failed", run.err)
        for char in self.UNSAFE:
            self.assertNotIn(char, run.err)

    def test_debug_and_trace_lines_are_ascii(self):
        message = "caf\u00e9 \x9b31m \u202eexe \u200b"
        run = run_cli(self, ["--debug", "search", "x"], http_error(500, {"message": message}))
        debug = [line for line in run.err.splitlines() if line.startswith("{")]
        self.assertTrue(debug and all(line.isascii() for line in debug))
        for char in ("\x9b", "\u202e", "\u200b"):
            self.assertNotIn(char, run.err)  # the plain error line is cleaned too
        written = "\n".join(trace_lines(run.config))
        self.assertTrue(written.isascii())
        errors = [json.loads(line) for line in trace_lines(run.config) if '"error"' in line]
        self.assertIn(message, errors[0]["error"])  # the original text survives, escaped


def config_of(root):
    config = root / "xdg" / "flx"
    config.mkdir(parents=True)
    return config


class S28SeenState(unittest.TestCase):
    def test_corrupt_state_warns_and_starts_fresh(self):
        root = temp_dir(self)
        config = config_of(root)
        (config / files.SEEN_FILE).write_text("{not json", encoding="utf-8")
        run = run_cli(self, ["scan", "--only-new"], ok(SEARCH_RESULT), keywords="n8n\n", root=root)
        self.assertEqual(run.code, 0)
        self.assertIn("unreadable", run.err)
        self.assertIn("Build an n8n workflow", run.out)
        self.assertEqual(files.load_seen(config), {101, 102})

    def test_state_that_cannot_be_saved_warns(self):
        root = temp_dir(self)
        (config_of(root) / files.SEEN_FILE).mkdir()  # a directory where the file should be
        run = run_cli(self, ["scan", "--only-new"], ok(SEARCH_RESULT), keywords="n8n\n", root=root)
        self.assertEqual(run.code, 0)
        self.assertIn("could not save", run.err)
        self.assertIn("Build an n8n workflow", run.out)

    def test_only_the_newest_ids_are_kept(self):
        base = temp_dir(self)
        files.save_seen(base, range(1, files.MAX_SEEN + 3))
        self.assertEqual(files.load_seen(base), set(range(3, files.MAX_SEEN + 3)))


class S29SearchInput(unittest.TestCase):
    def test_empty_search_text_is_refused_before_any_request(self):
        run = run_cli(self, ["search", "   "])
        self.assertEqual(run.code, cli.EXIT_ERROR)
        self.assertIn("empty", run.err)
        self.assertEqual(run.opener.requests, [])

    def test_limit_and_offset_are_checked_by_the_parser(self):
        for extra in (["--limit", "0"], ["--limit", "101"], ["--limit", "abc"], ["--offset", "-1"]):
            with self.subTest(extra=extra), self.assertRaises(SystemExit) as ctx:
                run_cli(self, ["search", "x", *extra])
            self.assertEqual(ctx.exception.code, 2)

    def test_limit_and_offset_reach_the_api(self):
        run = run_cli(self, ["search", "x", "--limit", "100", "--offset", "40"], ok(result_with()))
        query = query_of(run.opener.requests[0])
        self.assertEqual((query["limit"], query["offset"]), (["100"], ["40"]))


class S30ConfigDir(unittest.TestCase):
    def test_first_run_creates_a_private_config_dir_with_default_keywords(self):
        run = run_cli(self, ["scan", "--json"], *[ok(result_with()) for _ in files.DEFAULT_KEYWORDS])
        self.assertEqual(run.code, 0)
        self.assertEqual(stat.S_IMODE(run.config.stat().st_mode), 0o700)
        self.assertEqual(files.load_keywords(run.cwd, run.config), list(files.DEFAULT_KEYWORDS))
        queries = [query_of(r)["query"][0] for r in run.opener.requests]
        self.assertEqual(queries, list(files.DEFAULT_KEYWORDS))

    def test_an_existing_open_config_dir_is_tightened(self):
        root = temp_dir(self)
        config = config_of(root)
        config.chmod(0o775)  # what `mkdir -p` gives with umask 002
        run = run_cli(self, ["whoami"], ok({"username": "meric"}), root=root)
        self.assertEqual(run.code, 0)
        self.assertEqual(stat.S_IMODE(config.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((config / files.TRACE_DIR).stat().st_mode), 0o700)

    def test_seen_file_write_never_follows_a_planted_link(self):
        root = temp_dir(self)
        victim = root / "victim.txt"
        victim.write_text("keep me\n", encoding="utf-8")
        (config_of(root) / (files.SEEN_FILE + ".tmp")).symlink_to(victim)
        run = run_cli(self, ["scan", "--only-new"], ok(SEARCH_RESULT), keywords="n8n\n", root=root)
        self.assertEqual(run.code, 0)
        self.assertEqual(victim.read_text(encoding="utf-8"), "keep me\n")
        self.assertEqual(files.load_seen(run.config), {101, 102})
        leftovers = [p.name for p in run.config.iterdir() if p.name.endswith(".tmp") and not p.is_symlink()]
        self.assertEqual(leftovers, [])

    def test_existing_keywords_are_never_overwritten(self):
        root = temp_dir(self)
        (config_of(root) / files.KEYWORDS_FILE).write_text("my own term\n", encoding="utf-8")
        run = run_cli(self, ["scan", "--json"], ok(result_with()), root=root)
        self.assertEqual(json.loads(run.out)["keywords"], ["my own term"])
        self.assertEqual((run.config / files.KEYWORDS_FILE).read_text(encoding="utf-8"), "my own term\n")

    def test_keywords_in_cwd_override_the_config_dir(self):
        run = run_cli(self, ["scan", "--json"], ok(result_with()), keywords="local term\n")
        self.assertEqual(json.loads(run.out)["keywords"], ["local term"])

    def test_token_from_config_dir_works_from_any_directory(self):
        root = temp_dir(self)
        (config_of(root) / ".env.local").write_text(f"FREELANCER_TOKEN={TOKEN}\n", encoding="utf-8")
        run = run_cli(self, ["whoami"], ok({"username": "meric"}), token=None, root=root)
        self.assertEqual(run.code, 0)
        self.assertEqual(run.opener.requests[0].get_header("Freelancer-oauth-v1"), TOKEN)

    def test_state_and_traces_live_in_the_config_dir_not_in_cwd(self):
        run = run_cli(self, ["scan", "--only-new"], ok(SEARCH_RESULT), keywords="n8n\n")
        self.assertTrue((run.config / files.SEEN_FILE).is_file())
        self.assertTrue(list((run.config / files.TRACE_DIR).glob("*.jsonl")))
        self.assertEqual(sorted(p.name for p in run.cwd.iterdir()), ["keywords.txt", "skills.txt"])

    def test_config_dir_location(self):
        self.assertEqual(files.config_dir({"XDG_CONFIG_HOME": "/x/cfg", "HOME": "/h"}), Path("/x/cfg/flx"))
        self.assertEqual(files.config_dir({"HOME": "/h"}), Path("/h/.config/flx"))
        self.assertEqual(files.config_dir({"XDG_CONFIG_HOME": "relative", "HOME": "/h"}), Path("/h/.config/flx"))


class S32UntrustedFiles(unittest.TestCase):
    """.env.local and keywords.txt may come from a checkout flx does not own."""

    def test_env_file_that_is_not_a_small_regular_file_is_refused(self):
        cases = {
            "directory": lambda path: path.mkdir(),
            "too big": lambda path: path.write_text("#" * (files.MAX_FILE_BYTES + 1)),
            "not utf-8": lambda path: path.write_bytes(b"FREELANCER_TOKEN=\xff\xfe\n"),
        }
        if hasattr(os, "mkfifo"):
            cases["fifo"] = os.mkfifo  # would block a plain read forever
        for label, make in cases.items():
            with self.subTest(label):
                root = temp_dir(self)
                (root / "cwd").mkdir()
                make(root / "cwd" / ".env.local")
                run = run_cli(self, ["whoami"], token=None, root=root)
                self.assertEqual(run.code, cli.EXIT_ERROR)
                self.assertIn("Could not read", run.err)
                self.assertEqual(run.opener.requests, [])

    def test_keywords_file_that_is_too_big_is_refused(self):
        run = run_cli(self, ["scan"], keywords="n8n\n" + "#" * files.MAX_FILE_BYTES)
        self.assertEqual(run.code, cli.EXIT_ERROR)
        self.assertIn("larger than 64 KiB", run.err)
        self.assertEqual(run.opener.requests, [])

    def test_keywords_that_are_not_a_regular_file_fall_back_to_the_config_dir(self):
        root = temp_dir(self)
        (root / "cwd").mkdir()
        (root / "cwd" / files.KEYWORDS_FILE).mkdir()
        (config_of(root) / files.KEYWORDS_FILE).write_text("my own term\n", encoding="utf-8")
        run = run_cli(self, ["scan", "--json"], ok(result_with()), root=root)
        self.assertEqual(json.loads(run.out)["keywords"], ["my own term"])

    def test_at_most_fifty_keywords(self):
        terms = "".join(f"term {i}\n" for i in range(files.MAX_TERMS + 1))
        run = run_cli(self, ["scan"], keywords=terms)
        self.assertEqual(run.code, cli.EXIT_ERROR)
        self.assertIn("51 keywords; scan takes at most 50", run.err)
        self.assertEqual(run.opener.requests, [])
        terms = "".join(f"term {i}\n" for i in range(files.MAX_TERMS))
        outcomes = [ok(result_with()) for _ in range(files.MAX_TERMS)]
        self.assertEqual(run_cli(self, ["scan"], *outcomes, keywords=terms).code, 0)


SKILL_JOBS = [
    {"id": 3028, "name": "AI Agents"},
    {"id": 3106, "name": "AI Agent Swarms"},
    {"id": 95, "name": "Web Scraping"},
    {"id": 3172, "name": "ElevenAgents\x1b[2J"},
    {"id": "junk"},
]


class S34SkillsFile(unittest.TestCase):
    def test_first_run_creates_default_skills_that_scan_searches(self):
        outcomes = [ok(result_with()) for _ in files.DEFAULT_KEYWORDS + files.DEFAULT_SKILLS]
        run = run_cli(self, ["scan", "--json"], *outcomes, skills=None)
        self.assertEqual(run.code, 0)
        default_ids = [skill_id for skill_id, _ in files.DEFAULT_SKILLS]
        self.assertEqual(json.loads(run.out)["skills"], default_ids)
        text = (run.config / files.SKILLS_FILE).read_text(encoding="utf-8")
        self.assertIn("3028  # AI Agents", text)
        skill_queries = [query_of(r)["jobs[]"] for r in run.opener.requests if "jobs[]" in query_of(r)]
        self.assertEqual(skill_queries, [[str(i)] for i in default_ids])

    def test_default_skills_leave_out_the_ones_that_found_nothing_or_noise(self):
        default_ids = [skill_id for skill_id, _ in files.DEFAULT_SKILLS]
        self.assertEqual(default_ids, [3028, 3132, 2916, 3100, 95])
        for dropped in (3101, 3380, 3381):  # LLM Integration: 0 jobs live; the others: mostly noise
            self.assertNotIn(dropped, default_ids)

    def test_existing_skills_are_never_overwritten(self):
        root = temp_dir(self)
        (config_of(root) / files.SKILLS_FILE).write_text("95\n", encoding="utf-8")
        run = run_cli(self, ["scan", "--json"], ok(result_with()), skills=None, keywords="", root=root)
        self.assertEqual(json.loads(run.out)["skills"], [95])
        self.assertEqual((run.config / files.SKILLS_FILE).read_text(encoding="utf-8"), "95\n")

    def test_notes_blank_lines_and_repeats_are_skipped(self):
        root = temp_dir(self)
        (root / "cwd").mkdir()
        (root / "cwd" / files.SKILLS_FILE).write_text("# mine\n\n3028  # AI Agents\n 95\n3028\n", encoding="utf-8")
        self.assertEqual(files.load_skills(root / "cwd", config_of(root)), [3028, 95])

    def test_a_line_that_is_not_a_skill_id_stops_before_any_request(self):
        for bad in ("AI Agents", "-5", "0", "3.5", "１２"):
            with self.subTest(bad=bad):
                run = run_cli(self, ["scan"], keywords="n8n\n", skills=f"95\n{bad}\n")
                self.assertEqual(run.code, cli.EXIT_ERROR)
                self.assertIn("line 2", run.err)
                self.assertIn("flx skills", run.err)
                self.assertEqual(run.opener.requests, [])

    def test_at_most_fifty_skills(self):
        ids = "".join(f"{i}\n" for i in range(1, files.MAX_TERMS + 2))
        run = run_cli(self, ["scan"], keywords="", skills=ids)
        self.assertEqual(run.code, cli.EXIT_ERROR)
        self.assertIn("51 skills; scan takes at most 50", run.err)
        self.assertEqual(run.opener.requests, [])


class S35ScanWithSkills(unittest.TestCase):
    def test_skills_are_searched_after_keywords_and_merged(self):
        by_skill = result_with(
            {"id": 101, "title": "Build an n8n workflow", "time_submitted": 1790000000},  # also from n8n
            {"id": 201, "title": "AI agent for support", "time_submitted": 1790000900,
             "jobs": [{"id": 3028, "name": "AI Agents"}]},
        )
        run = run_cli(
            self, ["scan", "--json"], ok(SEARCH_RESULT), ok(by_skill), ok(result_with()),
            keywords="n8n\n", skills="3028\n95\n",
        )
        self.assertEqual(run.code, 0)
        keyword_request, *skill_requests = [query_of(r) for r in run.opener.requests]
        self.assertEqual(keyword_request["query"], ["n8n"])
        for query, skill_id in zip(skill_requests, ("3028", "95")):
            self.assertEqual(query["jobs[]"], [skill_id])
            self.assertNotIn("query", query)
            self.assertEqual((query["limit"], query["job_details"]), (["20"], ["true"]))
        self.assertEqual(run.sleeps, [1, 1])  # the gap applies to every search
        data = json.loads(run.out)
        self.assertEqual((data["keywords"], data["skills"]), (["n8n"], [3028, 95]))
        self.assertEqual([p["id"] for p in data["projects"]], [201, 102, 101])
        self.assertEqual(data["projects"][0]["skills"], ["AI Agents"])

    def test_skills_alone_are_enough(self):
        run = run_cli(self, ["scan", "--json"], ok(SEARCH_RESULT), keywords="# none\n", skills="95\n")
        self.assertEqual(run.code, 0)
        self.assertEqual(json.loads(run.out)["count"], 2)

    def test_a_failing_skill_is_skipped(self):
        run = run_cli(
            self, ["scan", "--json"], ok(SEARCH_RESULT), http_error(503), keywords="n8n\n", skills="95\n"
        )
        self.assertEqual(run.code, 0)
        data = json.loads(run.out)
        self.assertEqual((data["failed_keywords"], data["failed_skills"]), ([], [95]))
        self.assertIn("skill 95 failed", run.err)

    def test_client_refuses_a_bad_skill_id_before_sending(self):
        rig = make_client(self)
        for bad in (0, -3, "95", 9.5, True):
            with self.subTest(bad=bad), self.assertRaises(InvalidInputError):
                rig.client.search_skill(bad)
        self.assertEqual(rig.opener.requests, [])


class S36SkillsCommand(unittest.TestCase):
    def test_finds_skills_by_part_of_the_name(self):
        run = run_cli(self, ["skills", "AGENT"], ok(SKILL_JOBS))
        self.assertEqual(run.code, 0)
        self.assertEqual(
            run.out.splitlines(), ["  3028  AI Agents", "  3106  AI Agent Swarms", "  3172  ElevenAgents [2J"]
        )
        (request,) = run.opener.requests
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(urllib.parse.urlsplit(request.full_url).path, "/api/projects/0.1/jobs/")

    def test_json_and_no_match(self):
        data = json.loads(run_cli(self, ["skills", "scraping", "--json"], ok(SKILL_JOBS)).out)
        self.assertEqual(
            (data["schema_version"], data["command"], data["name"]), (SCHEMA_VERSION, "skills", "scraping")
        )
        self.assertEqual(data["skills"], [{"id": 95, "name": "Web Scraping"}])
        run = run_cli(self, ["skills", "welding"], ok(SKILL_JOBS))
        self.assertEqual(run.out, "No skills match 'welding'.\n")

    def test_empty_name_is_refused_before_any_request(self):
        run = run_cli(self, ["skills", "  "])
        self.assertEqual(run.code, cli.EXIT_ERROR)
        self.assertEqual(run.opener.requests, [])


class S31PartialScan(unittest.TestCase):
    KEYWORDS = "n8n\nzapier\ncrewai\n"
    FIRST = result_with({"id": 1, "title": "n8n job", "time_submitted": 100})
    THIRD = result_with({"id": 3, "title": "crewai job", "time_submitted": 300})

    def test_a_failing_keyword_is_skipped_and_the_rest_is_shown(self):
        # outcomes for zapier, and the sleeps around it: a timeout is retried once after 2 s, which
        # already makes the 1 s gap before crewai
        failures = {
            "timeout": ((TimeoutError("timed out"), TimeoutError("timed out")), [1, 2]),
            "network": ((urllib.error.URLError("Name or service not known"),), [1, 1]),
            "server error": ((http_error(503),), [1, 1]),
            "broken body": ((FakeResponse(b"<html>"),), [1, 1]),
        }
        for label, (failure, sleeps) in failures.items():
            with self.subTest(label):
                run = run_cli(self, ["scan", "--json"], ok(self.FIRST), *failure, ok(self.THIRD), keywords=self.KEYWORDS)
                self.assertEqual(run.code, 0)
                data = json.loads(run.out)
                self.assertEqual([p["id"] for p in data["projects"]], [3, 1])
                self.assertEqual(data["failed_keywords"], ["zapier"])
                self.assertIn("keyword 'zapier' failed", run.err)
                self.assertEqual(run.sleeps, sleeps)

    def test_failure_is_traced(self):
        run = run_cli(self, ["scan"], ok(self.FIRST), http_error(503), ok(self.THIRD), keywords=self.KEYWORDS)
        lines = [json.loads(line) for line in trace_lines(run.config)]
        warning = next(l for l in lines if l["step"] == "warning")
        self.assertIn("zapier", warning["message"])
        summary = next(l for l in lines if l["step"] == "scan")
        self.assertEqual((summary["failed"], summary["found"]), (1, 2))

    def test_only_new_marks_only_what_was_actually_fetched(self):
        run = run_cli(self, ["scan", "--only-new"], ok(self.FIRST), http_error(503), ok(self.THIRD), keywords=self.KEYWORDS)
        self.assertEqual(files.load_seen(run.config), {1, 3})

    def test_every_keyword_failing_is_an_error(self):
        run = run_cli(self, ["scan"], *[TimeoutError()] * 6, keywords=self.KEYWORDS)
        self.assertEqual(run.code, cli.EXIT_ERROR)
        self.assertEqual(run.out, "")
        self.assertIn("Every search failed (3 of 3)", run.err)

    def test_bad_token_still_stops_the_scan_at_once(self):
        run = run_cli(self, ["scan"], ok(self.FIRST), http_error(401), keywords=self.KEYWORDS)
        self.assertEqual(run.code, cli.EXIT_ERROR)
        self.assertEqual(run.out, "")
        self.assertEqual(len(run.opener.requests), 2)  # crewai was never searched


@unittest.skipUnless(hasattr(os, "mkfifo"), "needs FIFOs")
class S39SwappedFile(unittest.TestCase):
    """A file checked as regular but swapped for a FIFO before the read must not hang flx."""

    def read_in_thread(self, path):
        outcome = {}

        def run():
            try:
                outcome["text"] = files.read_small(path)
            except Exception as exc:  # noqa: BLE001 - the test inspects it
                outcome["error"] = exc

        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        worker.join(timeout=2)
        if worker.is_alive():  # unblock a reader stuck in open() so the thread can end
            os.close(os.open(path, os.O_WRONLY | os.O_NONBLOCK))
            self.fail("read_small blocked on a FIFO")
        return outcome

    def test_fifo_that_passed_a_path_check_is_refused_without_blocking(self):
        path = temp_dir(self) / ".env.local"
        os.mkfifo(path)
        # The path check says "regular file", as it would have just before the swap.
        with mock.patch.object(Path, "is_file", return_value=True), mock.patch.object(
            Path, "exists", return_value=True
        ):
            outcome = self.read_in_thread(path)
        self.assertIsInstance(outcome.get("error"), ValueError)
        self.assertEqual(str(outcome["error"]), "not a regular file")

    def test_regular_file_is_still_read(self):
        path = temp_dir(self) / files.KEYWORDS_FILE
        path.write_text("n8n\n", encoding="utf-8")
        self.assertEqual(self.read_in_thread(path), {"text": "n8n\n"})


class S40ScanContributionTrace(unittest.TestCase):
    def test_trace_counts_the_projects_each_term_added(self):
        run = run_cli(
            self, ["scan", "--json"],
            ok(SEARCH_RESULT),  # n8n: 101, 102
            ok(result_with({"id": 101}, {"id": 301}, {"id": 301})),  # zapier: one repeat, one new twice
            http_error(503),  # skill 95 fails, so it has no count
            ok(result_with({"id": 102}, {"title": "no id"})),  # skill 3028: a repeat and an id-less project
            keywords="n8n\nzapier\n", skills="95\n3028\n",
        )
        self.assertEqual(run.code, 0)
        (scan,) = [json.loads(line) for line in trace_lines(run.config) if json.loads(line)["step"] == "scan"]
        self.assertEqual(scan["new_by_keyword"], {"n8n": 2, "zapier": 1})
        self.assertEqual(scan["new_by_skill"], {"3028": 1})
        self.assertEqual(sum(scan["new_by_keyword"].values()) + sum(scan["new_by_skill"].values()), scan["found"])
        data = json.loads(run.out)
        self.assertEqual(data["count"], scan["found"])
        self.assertNotIn("new_by_keyword", data)  # trace only; the JSON output is unchanged


if __name__ == "__main__":
    unittest.main()
