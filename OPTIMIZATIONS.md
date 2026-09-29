# OPTIMIZATIONS - flx v0.1.0 pre-publish audit (2026-09-29)

Scope: `src/flx/*`, `tests/*`, `pyproject.toml`, `.github/workflows/test.yml`.

**Status (2026-09-29):** F1, F2 (approved by Meriç, recorded in DECISIONS.md) and F4-F8 are applied,
with tests. F3 and F9 were skipped: not worth measuring for now. Items marked **DECISIONS** change a recorded decision and need Meriç's OK first.
Security items live in `security.md`; two of them (unbounded body read, trace growth) are only
cross-referenced here.

## 1) Optimization Summary

Health is good for a tool of this size. There is no hot loop; wall time is almost entirely network
and deliberate pauses. Measured live on 2026-09-29: `scan` with 9 keywords took 21 s, of which
8 s is the fixed 1 s pause between keywords, and requests averaged about 1.4 s (earlier A/B: ~0.8 s
of each request is `owner_info`, kept on purpose). CPU work (parsing, rendering ~100 rows) is in the
milliseconds. `flx --help` starts in ~0.35 s, mostly the interpreter plus `ssl`/`urllib`.

Top 3 by ROI:
1. **Pause only the part of the 1 s that the request did not already use** (`scan` 21 s -> ~13 s). DECISIONS.
2. **One retry on timeout for a keyword** before skipping it: fewer holes in `scan` output on a slow API day.
3. **Single source for the version** before tagging `v0.1.0` (two places today, easy to tag a wrong one).

Biggest risk if nothing changes: nothing breaks. `scan` stays ~40% slower than it needs to be, and
on slow API days whole keywords silently drop out of the list the proposal agent sees
(`failed_keywords` records it, but the data is gone for that run).

## 2) Findings (Prioritized)

### F1. Fixed 1 s pause is added on top of request time
* **Category:** Network / Cost
* **Severity:** Medium
* **Impact:** `scan` latency
* **Evidence:** `commands.py:84-88`: `ctx.sleep(SCAN_PAUSE_S)` runs before every keyword after the first, regardless of how long the previous request took. Live: 9 keywords, 21 s total, 8 s of it sleeping.
* **Why it's inefficient:** the goal (DECISIONS: "API'yi yormamak, 429 riskini düşürmek") is a gap between requests. A request that already took 1.4 s satisfies a 1 s spacing by itself; the extra second adds nothing measurable against 429 at ~1 request per 1.4 s.
* **Recommended fix:** treat it as a minimum interval between request *starts*: remember `monotonic()` when a keyword starts, and before the next one sleep `max(0, SCAN_PAUSE_S - elapsed)`. Keep it injectable (`ctx.sleep`, plus a clock) so tests stay instant.
* **Tradeoffs / Risks:** request rate goes from ~1 per 2.4 s to ~1 per 1.4 s (still sequential, still at most 1/s). Changes the wording of a DECISIONS rule -> ask Meriç. Needs an updated scenario (pause shrinks when a request was slow, never negative).
* **Expected impact:** -8 s on a 9-keyword scan (~38%); grows linearly with keyword count.
* **Removal Safety:** Needs Verification (decision change)
* **Reuse Scope:** local file (`commands.py`)

### F2. A single timeout drops a whole keyword
* **Category:** Reliability
* **Severity:** Medium
* **Impact:** completeness of `scan` output
* **Evidence:** `client.py:163-166` raises `NetworkError` on the first timeout; `commands.py:89-91` then skips the keyword. PROGRESS Phase 5 notes live requests of 8-28 s against a 20 s timeout, so timeouts are real, not theoretical.
* **Why it's inefficient:** GET is idempotent and the slowness was transient; one retry would usually recover the keyword, whereas skipping loses 20 projects for that run.
* **Recommended fix:** in `Client.request`, retry once on a timeout (not on other network errors), with a short fixed wait (e.g. 2 s), traced as a `retry` step with `reason: "timeout"`. Leave the 429 policy untouched.
* **Tradeoffs / Risks:** worst case per keyword grows from 20 s to ~42 s. It is a new error-handling rule next to the 429 one in DECISIONS -> ask Meriç, add a scenario (timeout then 200 -> one result, two `http` trace lines).
* **Expected impact:** qualitative; turns most single-timeout keyword losses into successes.
* **Removal Safety:** Needs Verification
* **Reuse Scope:** module (`client.py`, all commands benefit)

### F3. New TCP + TLS connection for every request (likely)
* **Category:** Network
* **Severity:** Low (likely)
* **Impact:** per-request latency in `scan`
* **Evidence:** `client.py:75`: `urllib.request.build_opener(...).open` has no connection reuse; each keyword pays DNS + TCP + TLS handshake to `www.freelancer.com`.
* **Why it's inefficient:** 9 handshakes where 1 would do; typically 100-300 ms each from Europe, unmeasured here.
* **Recommended fix:** measure first: trace already has `duration_ms`; add a one-off timing of `socket.create_connection` + TLS handshake. Only if it is >150 ms, switch the transport to one `http.client.HTTPSConnection` kept for the Client's life (it never follows redirects, so `_NoRedirect` becomes unnecessary).
* **Tradeoffs / Risks:** rewrites the most security-sensitive code (GET-only guard, header handling, error mapping) and the S19 wire tests; must handle server-closed keep-alive connections. Likely not worth it before F1.
* **Expected impact:** likely 1-2.5 s on a 9-keyword scan; unproven.
* **Removal Safety:** Needs Verification
* **Reuse Scope:** module (`client.py`)

### F4. Version lives in two places
* **Category:** Build / Maintainability (Reuse Opportunity)
* **Severity:** Low
* **Impact:** release correctness
* **Evidence:** `pyproject.toml:7` `version = "0.1.0.dev0"` and `src/flx/__init__.py:3` `__version__ = "0.1.0.dev0"`. The `v0.1.0` tag needs both changed; `flx --version` and the `User-Agent` use `__init__`, pip metadata uses pyproject.
* **Why it's inefficient:** two edits per release, drift is silent (no test compares them).
* **Recommended fix:** `dynamic = ["version"]` in `[project]` and `[tool.setuptools.dynamic] version = {attr = "flx.__version__"}`; drop the literal from pyproject.
* **Tradeoffs / Risks:** none meaningful; CI's `pip install -e .` + `flx --version` step already verifies it.
* **Expected impact:** removes a class of release mistakes.
* **Removal Safety:** Safe
* **Reuse Scope:** build

### F5. Test suite spends ~1.2 s of 2.5 s waiting for a server to stop
* **Category:** Build (CI time, dev loop)
* **Severity:** Low
* **Impact:** test wall time, locally and 4x in CI
* **Evidence:** `tests/test_scenarios.py:472-474`: `server.serve_forever` uses the default `poll_interval=0.5`, and `server.shutdown` waits for the next poll. `--durations` shows the two S19 tests at 0.64 s and 0.60 s; every other test is <0.3 s.
* **Recommended fix:** `threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)`.
* **Tradeoffs / Risks:** none; slightly more idle polling during those two tests.
* **Expected impact:** full suite 2.5 s -> ~1.4 s (~45%).
* **Removal Safety:** Safe
* **Reuse Scope:** local file (tests)

### F6. Two different "no token" messages
* **Category:** Maintainability (Reuse Opportunity)
* **Severity:** Low
* **Evidence:** `auth.py:23` `MISSING_TOKEN` ("...in the environment or in .env.local.") is used only by `check_token` (`auth.py:43`); `load_token` (`auth.py:33-36`) builds a different, better message naming the config path. They have already drifted.
* **Recommended fix:** one message; `load_token` is the only path users hit, so make `MISSING_TOKEN` a function of `config` or have `check_token`'s empty case reuse the same wording.
* **Removal Safety:** Safe
* **Reuse Scope:** local file

### F7. Duplicated control-character filter in render
* **Category:** Maintainability (Reuse Opportunity)
* **Severity:** Low
* **Evidence:** `render.py:122` and `render.py:129` repeat `"".join(_DROP.get(unicodedata.category(c), c) for c in ...)`. This is the terminal-injection guard; two copies means a future fix can land in only one.
* **Recommended fix:** `def _strip_controls(text): return "".join(_DROP.get(unicodedata.category(c), c) for c in text)` used by both. (Smaller: `str(p.id) if p.id is not None else "-"` repeats in `detail` and `_cells`.)
* **Removal Safety:** Safe
* **Reuse Scope:** local file

### F8. Dead constant `EXIT_OK`
* **Category:** Dead Code
* **Severity:** Low
* **Evidence:** `cli.py:17` defines `EXIT_OK = 0`; nothing uses it (handlers `return 0`, `main` returns `code`).
* **Recommended fix:** remove it, or have handlers return `cli.EXIT_OK` (would be a circular import; removal is simpler).
* **Removal Safety:** Safe
* **Reuse Scope:** local file

### F9. `full_description` is fetched even when the table never shows it (likely)
* **Category:** Network
* **Severity:** Low (likely)
* **Evidence:** `client.py:48,81`: every `search`/`scan` asks for `full_description=true`; the table view (`render.table`) has no description column. Only `--json` and `project` use it.
* **Why it may matter:** bigger responses for 9 x 20 projects on each table-mode scan.
* **Recommended fix:** measure first, the way `owner_info` was measured (A/B `duration_ms` and body size). Only if the difference is material, pass `details` from the command (`full` only when `--json`).
* **Tradeoffs / Risks:** table and JSON calls would differ; a tiny extra parameter path. Probably not worth it; the proposal agent always uses `--json` anyway.
* **Removal Safety:** Needs Verification
* **Reuse Scope:** module

### Cross-referenced from security.md (not repeated in detail)
* Unbounded `response.read()` and uncaught `RecursionError` (`client.py:160,188`): Memory / Reliability, Low.
* Trace files grow without limit (`trace.py`): I/O / Cost, Low. A 30-day cleanup at start-up would bound it.
* Unlimited `keywords.txt` length drives one GET per line (`files.py:65-85`): Cost / abuse amplification, Low. A cap (e.g. 50) also bounds `scan` time.

### Checked and fine (no action)
* `merge_projects` is O(n log n) over ~180 items; `save_seen` sorts at most ~10k ints; trivial.
* `Tracer._write` does `mkdir` + open/append/close per line (~20-40 lines per run): < 1 ms each, and append-per-line is what keeps traces intact on a crash. Keep.
* Rendering: `display_width` is recomputed a few times per cell; ~100 rows, microseconds.
* Parallel keyword requests: faster, but contradicts the "API'yi yormamak" decision and raises 429 risk. Not recommended.
* Lazy-importing `urllib`/`ssl` to speed up `--help`: saves ~50 ms on a command that is never in a loop. Not worth the indirection.
* 429 backoff has no jitter: single sequential client, jitter buys nothing.
* No dependencies, so nothing to cache in CI.

## 3) Quick Wins (Do First)
1. F4 single version source (5 min, needed for the `v0.1.0` tag anyway).
2. F5 `poll_interval=0.05` in the S19 test server (1 line, ~45% faster suite).
3. F8 remove `EXIT_OK`, F6 unify the token message, F7 extract `_strip_controls` (10 min together, no behaviour change).

## 4) Deeper Optimizations (Do Next)
1. F1 start-to-start pacing in `scan` (after Meriç approves the DECISIONS wording).
2. F2 one retry on timeout (after Meriç approves; new scenario).
3. F3 connection reuse, only if a handshake measurement justifies touching `client.py`.
4. F9 conditional `full_description`, only if an A/B shows a material difference.

## 5) Validation Plan
* **Regression guard:** `python -m unittest discover -s tests` must pass in full after each item.
* **F1:** unit test with a fake clock: request "takes" 1.4 s -> no sleep; takes 0.3 s -> sleeps 0.7 s. Live: two `scan` runs before/after, compare the `end` trace line's `duration_ms` and check no `retry` (429) lines appear.
* **F2:** scenario test: fake opener raises `TimeoutError` once then returns 200 -> keyword present, `failed_keywords` empty, two `http` lines + one `retry` line with `reason: "timeout"`; twice -> skipped as today.
* **F3:** measure before deciding: time 9 fresh connections vs 9 requests on one connection (script outside the repo, GET only, same token path). Proceed only if the gap is > 150 ms per request.
* **F4:** `pip install -e . && flx --version` and `python -c "import importlib.metadata as m; print(m.version('flx'))"` print the same value (CI already runs the first).
* **F5:** `python -m unittest discover -s tests --durations 5` before/after; S19 tests should drop below 0.1 s.
* **F9:** A/B like the `owner_info` one: same query with and without `full_description`, compare `duration_ms` over ~5 runs each and response size.

## 6) Optimized Code / Patch (sketches, not applied)

F1, `commands.py` (needs a clock in `Context`, e.g. `monotonic: Callable[[], float] = time.monotonic`):
```python
last_start = None
for keyword in keywords:
    if last_start is not None:
        ctx.sleep(max(0.0, SCAN_PAUSE_S - (ctx.monotonic() - last_start)))
    last_start = ctx.monotonic()
    ...
```

F4, `pyproject.toml`:
```toml
[project]
name = "flx"
dynamic = ["version"]
...
[tool.setuptools.dynamic]
version = {attr = "flx.__version__"}
```

F5, `tests/test_scenarios.py:472`:
```python
threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
```

F7, `render.py`:
```python
def _strip_controls(text: str) -> str:
    return "".join(_DROP.get(unicodedata.category(c), c) for c in text)

def clean_line(text: str) -> str:
    return " ".join(_strip_controls(text).split())
```
