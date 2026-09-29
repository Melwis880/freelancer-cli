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
| 1 | Normal search | Projects parsed with id, title, link, type, budget min/max, currency, bid count, average bid, time submitted, client country, payment verified, description. Client country and payment status come from `owner_info` (requested with `owner_info=true`). Request is a GET to `projects/0.1/projects/active/` carrying the `Freelancer-OAuth-V1` header. |
| 2 | Empty result | Empty list, no error; also when `result` or `projects` is missing. |
| 3 | No token | Clear message naming `FREELANCER_TOKEN` and `.env.local`; no request is sent, for every command (exit 1). Order: environment variable, then `.env.local` in the working directory, then in the config dir; a blank variable falls through. |
| 4 | HTTP 401 | `AuthError` saying the token is invalid or expired; not retried; message never contains the token. |
| 5 | HTTP 429 | Waits 1, 2, 4 s (or `Retry-After`, capped at 10 s), at most 3 retries, then a clear "wait a minute" error. A successful retry returns normally. Other errors are not retried. |
| 6 | Network error or timeout | `NetworkError` ("Could not reach Freelancer"), timeouts say "timed out after 20 s"; not retried. |
| 7 | Broken JSON or missing fields | Non-JSON body is a clear `BadResponseError`, no traceback. Missing or wrongly typed fields come back as `None`; junk list items are skipped. |
| 8 | Non-GET request | `ReadOnlyError` before anything is sent, for every method but `GET`. The client has no write helpers. |
| 9 | Non-numeric project id | `InvalidInputError` before anything is sent (letters, signs, decimals, spaces, `0`, non-ASCII digits, over 12 digits). |
| 10 | Special characters in a search | `c++ & n8n` is sent as `query=c%2B%2B%20%26%20n8n`; a query cannot inject other parameters. |
| 11 | Same project from two keywords in `scan` | One record; newest first; undated projects last; nothing else dropped. |
| 12 | Token in the trace | Never written to the trace file or the `--debug` stream, even if an error message echoes it; long values are shortened. |
| 13 | `scan --only-new` twice | Second scan shows "No new projects."; only unseen ids are shown. `seen.json` in the config dir holds ids only. A plain `scan` never touches it, and a failed scan marks nothing as seen. |
| 14 | HTTP 404 on a project | `NotFoundError`: "Project <id> not found"; not retried. |
| 15 | `--debug` | Prints exactly the trace-file lines to stderr; without it, stderr has no trace lines but the file is still written. CLI error messages are masked. |
| 16 | Trace of one run | Steps linked by one `run_id` and consecutive `seq`, e.g. `http(429) -> retry -> http(200) -> result`; a failure ends with an `error` step; a CLI run has `start` and `end`. |
| 17 | Malformed token | Spaces, line breaks or non-ASCII in the token: clear error, token not echoed, no request (prevents header injection). |
| 18 | Other API errors | Error status shows the code and Freelancer's message; a `"status": "error"` body with HTTP 200 is also an error. |
| 19 | Redirects | Not followed, so the token header is never re-sent elsewhere. Also checks a real wire request is a GET with the token header. |
| 20 | Trace directory not writable | Command keeps running; one warning on stderr. |
| 21 | `whoami` | Prints "Token works. Logged in as <username>." and no other profile data. Missing username is an error. |
| 22 | Table | No row is wider than the terminal; titles start in the same column even with wide (CJK) characters and are cut with "…". A narrow terminal hides AVG, then COUNTRY, VERIFIED, BIDS, AGE, so the title keeps at least 24 columns. Hourly budgets end in "/h". Empty result says "No projects found." |
| 23 | `--json` | Top level has `schema_version`, `command`, `generated_at` and the command's inputs; every project has exactly the 13 fields of `models.Project`, `time_submitted` as ISO 8601 UTC. The field list is pinned to the schema version. |
| 24 | `project <id>` | Shows title, link, type, budget, bids with average, posting time and age, client country and payment status, full description. Missing fields do not break the view; a bad id fails before any request. |
| 25 | `scan` | Searches every keyword (20 results each) with a 1 s pause between keywords, merges and de-duplicates them newest first. |
| 26 | Empty `keywords.txt` | Clear error, no request. Blank lines, `#` comments and repeated terms (any case) are skipped. |
| 27 | Hostile text from the API | Escape sequences, control, bidi and zero-width characters in titles, descriptions, fields or error messages never reach the terminal. JSON escapes them and keeps the original text. |
| 28 | `seen.json` problems | Unreadable file: warning, every project treated as new, file rebuilt. Unwritable: warning, output still shown. Only the newest 10,000 ids are kept. |
| 29 | Bad search input | Empty search text fails before any request; `--limit` must be 1-100 and `--offset` 0 or more (usage error, exit 2). |
| 30 | Config dir | `$XDG_CONFIG_HOME/flx`, default `~/.config/flx` (a relative XDG path is ignored). First run creates it owner-only (700) with default `keywords.txt`; an existing list is never overwritten. `.env.local` and `keywords.txt` in the working directory override the config dir. `seen.json` and `traces/` always go to the config dir, never the working directory. |
