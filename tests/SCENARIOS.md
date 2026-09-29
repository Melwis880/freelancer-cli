# Scenarios

Every behaviour flx promises, and the test that proves it. Tests live in `tests/test_scenarios.py`
as one class per scenario (`S01...`). They use a fake HTTP opener and never touch the network,
except S19, which runs a throwaway server on 127.0.0.1.

Run all: `python -m unittest discover -s tests`

| # | Scenario | Expected |
|---|---|---|
| 1 | Normal search | Projects parsed with id, title, link, type, budget min/max, currency, bid count, average bid, time submitted, client country, payment verified, description. Request is a GET to `projects/0.1/projects/active/` carrying the `Freelancer-OAuth-V1` header. |
| 2 | Empty result | Empty list, no error; also when `result` or `projects` is missing. |
| 3 | No token | Clear message naming `FREELANCER_TOKEN` and `.env.local`; no request is sent. The environment variable wins over `.env.local`; a blank one falls back to the file. |
| 4 | HTTP 401 | `AuthError` saying the token is invalid or expired; not retried; message never contains the token. |
| 5 | HTTP 429 | Waits 1, 2, 4 s (or `Retry-After`, capped at 10 s), at most 3 retries, then a clear "wait a minute" error. A successful retry returns normally. Other errors are not retried. |
| 6 | Network error or timeout | `NetworkError` ("Could not reach Freelancer"), timeouts say "timed out after 20 s"; not retried. |
| 7 | Broken JSON or missing fields | Non-JSON body is a clear `BadResponseError`, no traceback. Missing or wrongly typed fields come back as `None`; junk list items are skipped. |
| 8 | Non-GET request | `ReadOnlyError` before anything is sent, for every method but `GET`. The client has no write helpers. |
| 9 | Non-numeric project id | `InvalidInputError` before anything is sent (letters, signs, decimals, spaces, `0`, non-ASCII digits, over 12 digits). |
| 10 | Special characters in a search | `c++ & n8n` is sent as `query=c%2B%2B%20%26%20n8n`; a query cannot inject other parameters. |
| 11 | Same project from two keywords in `scan` | One record; newest first; undated projects last; nothing else dropped. |
| 12 | Token in the trace | Never written to the trace file or the `--debug` stream, even if an error message echoes it; long values are shortened. |
| 13 | `scan --only-new` twice | Second scan does not show the same project again. *Phase 2, not built yet.* |
| 14 | HTTP 404 on a project | `NotFoundError`: "Project <id> not found"; not retried. |
| 15 | `--debug` | Prints exactly the trace-file lines to stderr; without it, stderr has no trace lines but the file is still written. CLI error messages are masked. |
| 16 | Trace of one run | Steps linked by one `run_id` and consecutive `seq`, e.g. `http(429) -> retry -> http(200) -> result`; a failure ends with an `error` step; a CLI run has `start` and `end`. |
| 17 | Malformed token | Spaces, line breaks or non-ASCII in the token: clear error, token not echoed, no request (prevents header injection). |
| 18 | Other API errors | Error status shows the code and Freelancer's message; a `"status": "error"` body with HTTP 200 is also an error. |
| 19 | Redirects | Not followed, so the token header is never re-sent elsewhere. Also checks a real wire request is a GET with the token header. |
| 20 | Trace directory not writable | Command keeps running; one warning on stderr. |
