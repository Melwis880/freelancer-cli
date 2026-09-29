# Case study: flx

## Problem

AI and automation jobs on Freelancer.com are buried in noise. A search for a tool like n8n or
LangChain also returns logo design, translation and data-entry jobs, so finding the few worth
bidding on means running the same searches by hand, again and again, and re-reading jobs already
seen.

The next step, a bidding agent that drafts proposals, needs more than a browser tab: it needs
clean, structured, de-duplicated data it can trust. The web pages are built for people, and the
official Python SDK is old, with unclear maintenance.

## Solution

`flx` is a small command-line tool, Python standard library only, that fetches job data from the
official Freelancer REST API and does nothing else.

- **Read-only by construction.** The HTTP client refuses every method but GET before a request is
  built, and does not follow redirects, so the token never leaves for another host. It cannot bid
  or message.
- **Polite to the API.** `scan` keeps keyword requests at least 1 s apart, start to start. On
  HTTP 429 it backs off 1, 2, 4 s (or honours `Retry-After`, capped at 10 s), retries at most 3
  times, then stops with a clear message. A timeout is retried once.
- **One command for the whole routine.** `flx scan --only-new` searches every term in
  `keywords.txt`, merges and de-duplicates the results, sorts newest first, and shows only jobs no
  earlier scan has shown.
- **Strict JSON for machines.** `--json` output carries a `schema_version` and a fixed set of 13
  fields per job, with a test that fails if the fields change without a version bump. Missing data
  comes back as `null` instead of crashing.
- **Standard, safe local files.** Token, keywords, seen ids and traces live in
  `~/.config/flx` (`$XDG_CONFIG_HOME`), created owner-only on first run. Every run writes a JSONL
  trace linked by `run_id`, and the token never appears in it.
- **Hostile input handled.** Control and escape characters from job titles are stripped before
  they reach the terminal.

Every behaviour is listed as a scenario in `tests/SCENARIOS.md`, each with an automated test
(102 tests, no network). The tests were checked by deliberately breaking the code: every break was
caught.

## Impact

First live run (2026-09-29), with the original 11-keyword list:

- 145 unique jobs from 11 searches in about 26 seconds, all HTTP 200, no rate limiting.
- A second `scan --only-new` returned no jobs: nothing is shown twice.
- The live check found that the API only sends client country and payment status inside
  `owner_info`, and only when it is asked for. It was fixed and verified the same day.

The keyword list has since been narrowed to niche terms (n8n, make.com, zapier, langchain, crewai,
...) to cut unrelated jobs; its effect has not been measured yet.

The result is a clean, de-duplicated, structured feed that a future bidding agent can consume
directly: it reads `flx scan --only-new --json`, and all filtering and scoring stays on the agent's
side.
