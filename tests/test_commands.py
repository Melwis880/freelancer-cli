"""Command scenarios from tests/SCENARIOS.md (S13, S21 onward, plus S3 at CLI level).

Every test runs the real CLI in-process against a fake API and a temp base dir; nothing touches the
network, the real environment or the repo's own .env.local.
"""

import copy
import dataclasses
import json
import stat
import unicodedata
import unittest
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import _path  # noqa: F401
from fakes import NOW, SEARCH_RESULT, TOKEN, http_error, ok, run_cli, temp_dir

from flx import SCHEMA_VERSION, cli, files, models, render

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
        self.assertEqual(SCHEMA_VERSION, 1)
        self.assertEqual([f.name for f in dataclasses.fields(models.Project)], PROJECT_FIELDS)

    def test_project_and_scan_json(self):
        project = json.loads(run_cli(self, ["project", "101", "--json"], ok(SEARCH_RESULT)).out)
        self.assertEqual((project["schema_version"], project["command"]), (SCHEMA_VERSION, "project"))
        self.assertEqual(list(project["project"]), PROJECT_FIELDS)
        self.assertEqual(project["project"]["client_country"], "Germany")

        scan = json.loads(run_cli(self, ["scan", "--json"], ok(SEARCH_RESULT), keywords="n8n\n").out)
        self.assertEqual(scan["keywords"], ["n8n"])
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

    def test_repo_keywords_file_matches_the_defaults(self):
        repo = _path.SRC.parent
        self.assertEqual(files.load_keywords(repo, repo), list(files.DEFAULT_KEYWORDS))


class S26Keywords(unittest.TestCase):
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
        self.assertEqual(sorted(p.name for p in run.cwd.iterdir()), ["keywords.txt"])

    def test_config_dir_location(self):
        self.assertEqual(files.config_dir({"XDG_CONFIG_HOME": "/x/cfg", "HOME": "/h"}), Path("/x/cfg/flx"))
        self.assertEqual(files.config_dir({"HOME": "/h"}), Path("/h/.config/flx"))
        self.assertEqual(files.config_dir({"XDG_CONFIG_HOME": "relative", "HOME": "/h"}), Path("/h/.config/flx"))


if __name__ == "__main__":
    unittest.main()
