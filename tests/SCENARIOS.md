# Scenarios

Every behaviour flx promises, and the test that proves it. Each scenario is a test class named
after its number (`S01...`): the core in `tests/test_scenarios.py`, the commands in
`tests/test_commands.py`. They use a fake HTTP opener and never touch the network, except S19,
which runs a throwaway server on 127.0.0.1. Command tests also run in a temp working directory with a temp
`XDG_CONFIG_HOME` and their own environment, so the real token, `~/.config/flx` and the repo's
`.env.local` are never read or written.

Run all: `python -m unittest discover -s tests`

| # | Scenario | Expected |
|---|---|---|
| 1 | Normal search | Projects parsed with id, title, link, type, budget min/max, currency, bid count, average bid, time submitted, client country, payment verified, description, skills (names from `jobs`, requested with `job_details=true`; a job without a name is skipped). Client country and payment status come from `owner_info` (requested with `owner_info=true`). Request is a GET to `projects/0.1/projects/active/` carrying the `Freelancer-OAuth-V1` header. |
| 2 | Empty result | Empty list, no error; also when `result` or `projects` is missing. |
| 3 | No token | Clear message naming `FREELANCER_TOKEN` and `.env.local` (one wording everywhere); no request is sent, for every command (exit 1). Order: environment variable, then `.env.local` in the working directory, then in the config dir; a blank variable falls through. |
| 4 | HTTP 401 | `AuthError` saying the token is invalid or expired; not retried; message never contains the token. |
| 5 | HTTP 429 | Waits 1, 2, 4 s (or `Retry-After`, capped at 10 s), at most 3 retries, then a clear "wait a minute" error. A successful retry returns normally. Other errors are not retried. |
| 6 | Network error or timeout | `NetworkError` ("Could not reach Freelancer"). A timeout is retried once after 2 s (traced as `retry` with `reason: "timeout"`); a second timeout says "timed out after 20 s". Other network errors are not retried. |
| 7 | Broken JSON or missing fields | Non-JSON body is a clear `BadResponseError`, no traceback. Missing or wrongly typed fields come back as `None`; junk list items are skipped. |
| 8 | Non-GET request | `ReadOnlyError` before anything is sent, for every method but `GET`. The client has no write helpers. |
| 9 | Non-numeric project id | `InvalidInputError` before anything is sent (letters, signs, decimals, spaces, `0`, non-ASCII digits, over 12 digits). |
| 10 | Special characters in a search | `c++ & n8n` is sent as `query=c%2B%2B%20%26%20n8n`; a query cannot inject other parameters. |
| 11 | Same project from two keywords in `scan` | One record; newest first; undated projects last; nothing else dropped. |
| 12 | Token in the trace | Never written to the trace file or the `--debug` stream, even if an error message echoes it; long values are shortened. |
| 13 | `scan --only-new` twice | Second scan shows "No new projects."; only unseen ids are shown. `seen.json` in the config dir holds ids only. A plain `scan` never touches it, and a failed scan marks nothing as seen. |
| 14 | HTTP 404 on a project | `NotFoundError`: "Project <id> not found"; not retried. |
| 15 | `--debug` | Prints exactly the trace-file lines to stderr; without it, stderr has no trace lines but the file is still written. CLI error messages are masked. |
| 16 | Trace of one run | Steps linked by one `run_id` and consecutive `seq`, e.g. `http(429) -> retry -> http(200) -> result`, each `retry` naming its `reason` (`rate_limit` or `timeout`); a failure ends with an `error` step; a CLI run has `start` and `end`. |
| 17 | Malformed token | Spaces, line breaks or non-ASCII in the token: clear error, token not echoed, no request (prevents header injection). |
| 18 | Other API errors | Error status shows the code and Freelancer's message; a `"status": "error"` body with HTTP 200 is also an error. |
| 19 | Redirects | Not followed, so the token header is never re-sent elsewhere. Also checks a real wire request is a GET with the token header. |
| 20 | Trace directory not writable | Command keeps running; one warning on stderr. |
| 21 | `whoami` | Prints "Token works. Logged in as <username>." and no other profile data. Missing username is an error. |
| 22 | Table | No row is wider than the terminal; titles start in the same column even with wide (CJK) characters and are cut with "…". A narrow terminal hides AVG, then COUNTRY, VERIFIED, BIDS, AGE, so the title keeps at least 24 columns. Hourly budgets end in "/h". Empty result says "No projects found." |
| 23 | `--json` | Top level has `schema_version` (3), `command`, `generated_at` and the command's inputs; every project has exactly the 14 fields of `models.Project`, `time_submitted` as ISO 8601 UTC. The field list is pinned to the schema version. |
| 24 | `project <id>` | Shows title, link, type, budget, bids with average, posting time and age, client country and payment status, skills, full description. Missing fields do not break the view; a bad id fails before any request. |
| 25 | `scan` | Searches every keyword, then every skill (20 results each), merges and de-duplicates them newest first. Requests start at least 1 s apart, measured start to start: a request that took longer is not followed by an extra pause. |
| 26 | Empty `keywords.txt` | Fine if `skills.txt` has ids (skills only); if both are empty, a clear error and no request. Blank lines, `#` comments and repeated terms (any case) are skipped. The default list holds single niche terms only: the API matches multi-word terms loosely (live check 2026-09-30). |
| 27 | Hostile text from the API | Escape sequences, control, bidi and zero-width characters in titles, descriptions, fields, error messages or `scan` warnings never reach the terminal. JSON escapes them and keeps the original text. Trace lines (file and `--debug`) are pure ASCII, non-ASCII escaped. |
| 28 | `seen.json` problems | Unreadable file: warning, every project treated as new, file rebuilt. Unwritable: warning, output still shown. Only the newest 10,000 ids are kept. |
| 29 | Bad search input | Empty search text fails before any request; `--limit` must be 1-100 and `--offset` 0 or more (usage error, exit 2). |
| 30 | Config dir | `$XDG_CONFIG_HOME/flx`, default `~/.config/flx` (a relative XDG path is ignored). First run creates it owner-only (700) with default `keywords.txt` and `skills.txt`; an existing dir that is open to others (e.g. from `mkdir -p`) is tightened to 700, `traces/` is 700 too; an existing list is never overwritten. `seen.json` is replaced via a fresh, randomly named temp file, so a planted `seen.json.tmp` link is never followed. `.env.local` and `keywords.txt` in the working directory override the config dir. `seen.json` and `traces/` always go to the config dir, never the working directory. |
| 31 | Partial failure during `scan` | A keyword or skill search that fails with a network error, timeout (after its one retry), server error or broken body is skipped: a warning names it on stderr and in the trace, the other keywords are still searched (with the pause), and the results that did arrive are shown. JSON lists it in `failed_keywords`; `--only-new` marks only fetched projects as seen. If every keyword fails, exit 1 with nothing on stdout. A bad token (401) or an exhausted rate limit still stops the scan at once. |
| 32 | Files from an untrusted folder | `.env.local`, `keywords.txt` and `skills.txt` must be regular UTF-8 files of at most 64 KiB, otherwise a clear error and no request (a FIFO or `/dev/zero` cannot hang flx). A `keywords.txt` in the working directory that is not a regular file is ignored in favour of the config dir. `scan` takes at most 50 keywords and 50 skills. |
| 33 | Hostile response body | A body over 10 MiB is not read past the limit and gives a clear `BadResponseError`; absurdly deep JSON nesting is a `BadResponseError`, not a traceback. |
| 34 | `skills.txt` | One Freelancer skill id per line; text after `#` is a note, blank lines and repeats are skipped. First run writes a default list (AI Agents, Agentic AI, AI Chatbot Development, LLM Integration, RAG, Web Scraping), never overwritten; the working directory's file overrides. A line that is not a positive id stops the scan before any request, naming the line and `flx skills`. |
| 35 | `scan` with skills | Each skill is its own request: `jobs[]=<id>`, no `query`, 20 results, same 1 s spacing as keywords. Results merge with the keyword results. JSON lists `skills` and `failed_skills`; a failing skill is skipped with a warning. The client refuses a skill id that is not a positive int before sending. |
| 36 | `flx skills <name>` | One GET to `projects/0.1/jobs/`; prints id and name of every skill whose name contains the text (any case), cleaned for the terminal; says so when none match; `--json` gives `{"id", "name"}` pairs. Empty name fails before any request. |
| 37 | Project link | `url` is `https://www.freelancer.com/projects/<seo_url>` only when every `/`-separated part of `seo_url` is letters, digits and `-_.~`; an empty, `.` or `..` part, or `?`, `#`, `%`, `@`, `\`, `:`, spaces or control characters give `url: null` so a hostile value cannot point the link elsewhere. The rest of the project is kept. |
| 38 | Trace permissions | `traces/` is 700 and each `YYYY-MM-DD.jsonl` is 600, also under umask 002. An existing `traces/` or trace file that others can read (e.g. 775/664 from before this rule) is tightened on the next write; its earlier lines are kept. |
| 39 | File swapped after the check | `.env.local`, `keywords.txt` and `skills.txt` are opened first (non-blocking) and the opened file must be a regular file, so a FIFO swapped in after any path check is refused at once ("not a regular file") instead of hanging flx. A regular file is read as before. |
| 40 | Per-term contribution in the `scan` trace | The `scan` trace line has `new_by_keyword` and `new_by_skill`: for each term that did not fail, how many projects it added that no earlier term had (a repeat counts for the first term; a project without an id always counts). The counts sum to `found`. The `--json` output does not change. |
