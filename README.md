# flx

A read-only command-line tool that finds AI and automation jobs on
[Freelancer.com](https://www.freelancer.com) and returns them as clean data, for a person at a
terminal or for another program (such as a proposal-writing agent).

```
$ flx scan --only-new
      ID  AGE           BUDGET  BIDS    AVG  COUNTRY      VERIFIED  TITLE
40000003   1h      250-750 USD    18    412  Germany      yes       n8n workflow to sync CRM leads …
40000002   5h  1,500-3,000 EUR    41  2,210  Netherlands  yes       LangChain RAG assistant over in…
40000001   1d      15-25 USD/h     7     20  Canada       no        Python web scraping for product…
```

## Why

Finding the few jobs worth bidding on means running the same searches over and over and
re-reading jobs you have already seen. `flx` runs your whole keyword list in one command, merges
and de-duplicates the results, puts the newest first, and can show only jobs you have not seen
before.

It only fetches data. It does not filter, score or rank jobs; that is left to whatever reads
its output.

## Read-only by design

- The HTTP client sends `GET` only. Any other method fails in code before a request is built,
  so `flx` cannot bid, message or change anything on your account.
- Redirects are not followed, so the token is never re-sent to another host.
- The token is never printed, logged or written to traces. It is masked in error messages.
- Text from the API is stripped of control and escape characters before it reaches your
  terminal. `--json` keeps the original text, escaped.
- No third-party dependencies: Python standard library only.

## Install

Requires Python 3.10 or newer.

```bash
git clone <this repo> && cd freelancer-cli
pip install -e .
flx --version
```

Without installing, `PYTHONPATH=src python -m flx ...` works from the repo folder.

## Token

1. Create an app in the Freelancer developer settings
   (`https://accounts.freelancer.com/settings/develop`) and give it read access only.
2. Save the token without it showing on screen or in your shell history:

```bash
mkdir -p ~/.config/flx
read -rs T && printf 'FREELANCER_TOKEN=%s\n' "$T" > ~/.config/flx/.env.local && unset T
chmod 600 ~/.config/flx/.env.local
flx whoami        # Token works. Logged in as <your username>.
```

`flx` looks for the token in this order: the `FREELANCER_TOKEN` environment variable,
`.env.local` in the current directory, then `~/.config/flx/.env.local`.

## Usage

| Command | What it does |
|---|---|
| `flx whoami` | Checks the token; prints your username only. |
| `flx search "<text>" [--limit N] [--offset N] [--json]` | Searches active projects. `--limit` 1-100, default 20. |
| `flx project <id> [--json]` | One project in full: link, budget, bids, client country and payment status, description. |
| `flx scan [--only-new] [--json]` | Searches every term in `keywords.txt` (20 results each, 1 s apart), merged, de-duplicated, newest first. A keyword that fails (network, timeout, server error) is skipped with a warning; the rest is still shown. |

`--only-new` shows only projects that no earlier `--only-new` scan has shown. Seen project ids
are kept in `seen.json`; a plain `scan` never touches it.

The table fits your terminal width: long titles are cut, and on a narrow terminal the AVG,
COUNTRY, VERIFIED, BIDS and AGE columns hide in that order. Hourly budgets end in `/h`.

Global flag: `--debug` also prints trace lines to stderr.

Exit codes: `0` success, `1` error (message on stderr), `2` usage error.

See [`examples/`](examples/) for full sample output. It uses made-up data.

## JSON output

Every `--json` output has a `schema_version` (currently `2`). It is bumped whenever a field
changes, so programs reading it can detect breaking changes.

```json
{
  "schema_version": 1,
  "command": "search",
  "generated_at": "2026-09-21T16:13:20Z",
  "query": "automation", "limit": 3, "offset": 0,
  "count": 3,
  "projects": [ { "id": 40000003, "title": "...", "...": "..." } ]
}
```

`scan` has `keywords`, `failed_keywords` and `only_new` instead of `query`/`limit`/`offset`. `project` has a
single `project` instead of `projects`/`count`.

Each project:

| Field | Type | Notes |
|---|---|---|
| `id` | int | |
| `title` | string | |
| `url` | string | Link to the job on freelancer.com |
| `type` | string | `fixed` or `hourly` |
| `budget_min`, `budget_max` | number | In `currency` |
| `currency` | string | e.g. `USD` |
| `bid_count` | int | |
| `bid_avg` | number | Average bid, in `currency` |
| `time_submitted` | string | ISO 8601, UTC |
| `client_country` | string | |
| `payment_verified` | bool | Client has a verified payment method |
| `description` | string | Full description |

Any field can be `null` when Freelancer does not send it.

## Files

Everything lives in `~/.config/flx/` (or `$XDG_CONFIG_HOME/flx`). The folder is created on
first run, readable only by you:

| File | Purpose |
|---|---|
| `.env.local` | Your token |
| `keywords.txt` | Search terms for `scan`, one per line (`#` for comments). A default list is created on first run and never overwritten. |
| `seen.json` | Project ids already shown by `scan --only-new` (ids only, newest 10,000) |
| `traces/YYYY-MM-DD.jsonl` | Trace log |

A `.env.local` or `keywords.txt` in the current directory overrides the one in
`~/.config/flx/`.

## Traces

Every run appends one JSON line per step to `traces/YYYY-MM-DD.jsonl`: HTTP call (endpoint,
parameters, status, duration), retry, result count, error. All lines of one run share a
`run_id` and are numbered by `seq`. The token never appears in traces, and long values are
shortened.

If Freelancer returns HTTP 429 (rate limit), `flx` waits 1, 2 and then 4 seconds (or what
`Retry-After` asks, at most 10 s), retries up to 3 times, then stops with a clear message.

## Development

```bash
python -m unittest discover -s tests
```

The tests never touch the network, your real token or `~/.config/flx`. Every behaviour is
listed in [`tests/SCENARIOS.md`](tests/SCENARIOS.md) with the test that covers it.

## License

MIT, see [LICENSE](LICENSE).
