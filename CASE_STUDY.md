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
- **Polite to the API.** `scan` keeps its requests at least 1 s apart, start to start. On
  HTTP 429 it backs off 1, 2, 4 s (or honours `Retry-After`, capped at 10 s), retries at most 3
  times, then stops with a clear message. A timeout is retried once.
- **One command for the whole routine.** `flx scan --only-new` searches every term in
  `keywords.txt` and every Freelancer skill in `skills.txt`, merges and de-duplicates the results, sorts newest first, and shows only jobs no
  earlier scan has shown.
- **Strict JSON for machines.** `--json` output carries a `schema_version` and a fixed set of 14
  fields per job, with a test that fails if the fields change without a version bump. Missing data
  comes back as `null` instead of crashing.
- **Standard, safe local files.** Token, keywords, seen ids and traces live in
  `~/.config/flx` (`$XDG_CONFIG_HOME`), created owner-only on first run. Every run writes a JSONL
  trace linked by `run_id`, and the token never appears in it.
- **Hostile input handled.** Control and escape characters from job titles are stripped before
  they reach the terminal.

Every behaviour is listed as a scenario in `tests/SCENARIOS.md`, each with an automated test
(123 tests, no network). The tests were checked by deliberately breaking the code: every break was
caught.

## Impact

First live run (2026-09-29), with the original 11-keyword list:

- 145 unique jobs from 11 searches in about 26 seconds, all HTTP 200, no rate limiting.
- A second `scan --only-new` returned no jobs: nothing is shown twice.
- The live check found that the API only sends client country and payment status inside
  `owner_info`, and only when it is asked for. It was fixed and verified the same day.

Relevance, measured (2026-09-30): a scan with niche keywords plus multi-word terms ("llm
integration", "python web scraping") returned about half unrelated jobs. Searching each term alone
showed why: the API matches multi-word text loosely, and those four terms found their phrase in 1 of
80 results. They were replaced by skill searches, which match exactly. Each skill was then checked
on its own and kept only if most of its jobs were on target: "AI Automation" came back about half
video and sales work and was dropped for "AI Chatbot Development" and "Agentic AI". The final list
(AI Agents, Agentic AI, AI Chatbot Development, LLM Integration, RAG, Web Scraping, plus the five
niche keywords) gave 83 jobs from 11 requests in 14 s. Read one by one, about 56 are clearly on
target, 7 are borderline (manual list-building) and 20 are off target, mostly jobs that tag Zapier
or AI for admin, sales or marketing work. That rest is left to the agent: each job now lists its
skills, so the agent can filter on them. LLM Integration was dropped afterwards: it returned 0
jobs in every live scan, so it cost a request for nothing.

The result is a clean, de-duplicated, structured feed that a future bidding agent can consume
directly: it reads `flx scan --only-new --json`, and all filtering and scoring stays on the agent's
side.

## Part 2: the agent on top

`flx` was built to feed one consumer: a bidding agent that turns raw jobs into decisions and
proposal drafts. That agent now runs in my private agent workspace. Its code is not in this repo;
this section describes how it works and what its first real run produced.

### How it works

The agent is a Claude Code agent defined in plain Markdown: one identity file and two skills,
"screen listings" and "write a proposal", plus a criteria file. It runs only when I ask.

1. **Scan to a file first.** It runs `flx scan --json` and saves the raw output before reading a
   single job, so every decision can be traced back to the data it was made on.
2. **Treat job text as untrusted.** Clients write job descriptions, so each one is checked for
   hidden Unicode (tag characters, zero-width and bidi controls) and for lines addressed to an AI.
   A hit stops the run. Job text is read as data, never followed as an instruction.
3. **Decide every job.** A core test (the deliverable is runnable code or configuration, it does
   not depend on clicking around in the client's accounts, it automates a measurable business
   process), three tiers, a budget floor, and a hard-reject list (fake traffic, review
   manipulation, collecting personal data without consent). Each job gets one of three decisions:
   bid, ask me, or skip, with a one-line reason.
4. **Draft only what passes.** Proposals are written in the job's language, open with the
   client's problem, give a 3-5 step approach that can be tested, and cite only proof that exists
   publicly. If a claim is not on my public proof list, it is left out.
5. **Never send.** Sending a bid stays with me, by hand. The agent is not allowed to bid or
   message, and `flx` cannot send anything by construction.

### First run (2026-09-30)

- 84 jobs from 11 searches (5 keywords, 6 skills), no failed search.
- Every job got a decision: **8 bid, 34 ask me, 42 skip**.
- The 34 "ask me" jobs came back grouped into 9 questions (interface-heavy platform setup, broad
  builds, server or money-system access, and so on), so I could decide them by group, not one by
  one.
- 2 proposal drafts in the run, 3 more on request the same day.
- The agent also flagged gaps in its own rules instead of working around them silently. For
  example, 16 of the 20 "Web Scraping" jobs were skipped as list-building or data entry, and the
  scoring did not reward fit with my route. Each fix was proposed, none applied without my "yes".

What it does not prove yet: no time comparison (I never screened these jobs by hand at this
volume), and no bid outcomes so far. Both will be added only when they are measured.
