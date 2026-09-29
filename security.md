### SECURITY AUDIT: flx v0.1.0 pre-publish, whole codebase + git history (2026-09-29)

**Risk Assessment:** Medium (no secrets found; one permissions gap that contradicts DECISIONS.md, one privacy item for the first push, the rest Low)

**Status (2026-09-29):** every finding below is fixed and covered by a scenario test (S25-S33 in
`tests/SCENARIOS.md`); the commit e-mail was replaced with a GitHub noreply address before the
first push. Observations were left as they are unless noted.

Scope: `src/flx/*`, `tests/*`, `README.md`, `.github/workflows/test.yml`, `pyproject.toml`, all 12 commits
(`git log -p --all`), and the live `~/.config/flx` on the dev machine.

#### **Findings:**

* **Config dir permissions not enforced; README creates it group-writable** (Severity: Medium)
  * **Location:** `src/flx/files.py:51` (`ensure_config`), `src/flx/trace.py:83` (`_write`), `src/flx/files.py:106-110` (`save_seen`), `README.md:54`
  * **The Exploit:** DECISIONS.md promises a `700` config dir, but `mkdir(mode=0o700, exist_ok=True)` does nothing to a dir that already exists. The README tells users to run `mkdir -p ~/.config/flx` *before* the first `flx` run, so with the common `umask 002` the dir is born `775`. Verified on the dev machine: `~/.config/flx` is `775`, `traces/` `775`, trace files `664` (only `.env.local` is `600`, thanks to the README's `chmod`). On a machine where the user's group has other members (shared servers, `umask 002` + shared group), any group member can: plant or replace `.env.local`/`keywords.txt`; read traces (search history); pre-create `seen.json.tmp` as a symlink, and the next `scan --only-new` (`tmp.write_text` follows symlinks) overwrites the linked file of the victim with JSON. The `printf ... > .env.local` step also leaves the token `664` for a moment before `chmod 600`. Local exposure on this machine: none (the user's own group has no other members), but every other user of the published tool inherits the gap.
  * **The Fix:**
    ```python
    # files.py, ensure_config
    config.mkdir(mode=0o700, parents=True, exist_ok=True)
    if config.stat().st_uid == os.getuid() and config.stat().st_mode & 0o077:
        os.chmod(config, 0o700)   # tighten a dir created by `mkdir -p` or an old flx
    # trace.py, _write
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    # files.py, save_seen: open the tmp file with O_CREAT|O_EXCL|O_NOFOLLOW (or unlink it first)
    ```
    README: `mkdir -p -m 700 ~/.config/flx` and write the token under `(umask 077; read -rs T && printf ... > ...)`. Optional: warn when `.env.local` is group/world-readable (like ssh does). Needs a scenario + test (dir pre-created `775` becomes `700`).

* **Commit author e-mail becomes public on first push** (Severity: Medium, privacy)
  * **Location:** all 12 commits, author and committer carry a personal e-mail address
  * **The Exploit:** a public repo exposes the address to anyone (`git log`, GitHub API, `.patch` URLs); scrapers harvest it for spam/phishing and it links this project to the personal account. Cannot be undone after the push without a force-push, and forks/caches keep it.
  * **The Fix:** decide *before* the first push. Either accept it, or set `git config user.email <id>+<user>@users.noreply.github.com` and rewrite the 12 local commits (`git rebase -r --root --exec 'git commit --amend --no-edit --reset-author'`) while nothing is published yet. Enable "Block command line pushes that expose my email" on GitHub.

* **Unsanitised API text reaches the terminal via `scan` warnings** (Severity: Low)
  * **Location:** `src/flx/commands.py:47-49` (`Context.warn`), called from `commands.py:91`
  * **The Exploit:** `ApiError` messages embed `message[:200]` from the server's error body (`client.py:254-256`). `cli.main` prints errors through `clean_line(tracer.scrub(...))`, but `warn` prints raw, so a hostile or compromised API response (or a future endpoint that echoes user content) can put ANSI/OSC escapes on stderr: rewrite earlier lines, set the window title, or emit OSC 52 clipboard writes on terminals that allow it. Breaks the terminal-injection rule in DECISIONS.md for this one path.
  * **The Fix:** `print(f"flx: {render.clean_line(self.tracer.scrub(message))}", file=sys.stderr)` in `warn`; add a scenario (API error body with `\x1b[2J` during `scan` does not reach stderr raw).

* **`--debug` stderr copy passes C1 controls and bidi/zero-width characters** (Severity: Low)
  * **Location:** `src/flx/trace.py:63-66`
  * **The Exploit:** `json.dumps(..., ensure_ascii=False)` escapes C0 (`\x1b`) but emits U+0080-U+009F (U+009B is an 8-bit CSI on some terminals), U+202E (right-to-left override) and zero-width characters verbatim. Trace records carry server error messages and the `--debug` copy goes straight to the terminal; `cat`-ing a trace file has the same effect.
  * **The Fix:** use `ensure_ascii=True` (at least for the stderr copy; simplest for both, traces stay valid JSON and greppable).

* **Current-directory overrides trust whatever folder `flx` runs in** (Severity: Low)
  * **Location:** `src/flx/auth.py:30,57-63`, `src/flx/files.py:59-85`
  * **The Exploit:** running `flx` inside an untrusted checkout: (a) a planted `.env.local` silently wins over the user's own token (session confusion, `whoami` shows the attacker's account); (b) `.env.local` as a symlink to `/dev/zero` or a FIFO makes `read_text` hang or eat all memory (`keywords.txt` is protected by `is_file()`, `.env.local` is not); (c) a planted `keywords.txt` with thousands of lines makes `scan` send thousands of GETs under the user's token (one per second, for hours), risking rate limiting or an API ban on the user's account. The token itself cannot leak (host is fixed), so this is nuisance/DoS only.
  * **The Fix:** check `is_file()` and a size cap (e.g. 64 KiB) before reading `.env.local`/`keywords.txt`; cap the keyword count (e.g. 50) with a clear error. Changing *whether* cwd files override is a DECISIONS.md item; ask Meriç first.

* **Unbounded response read and uncaught `RecursionError`** (Severity: Low)
  * **Location:** `src/flx/client.py:160,188`
  * **The Exploit:** `response.read()` has no size limit, and `json.loads` on deeply nested JSON raises `RecursionError`, which is not a `ValueError`, so it escapes as a traceback. Needs a hostile server behind valid TLS for `www.freelancer.com`; robustness more than security.
  * **The Fix:** `response.read(MAX_BODY + 1)` with e.g. `MAX_BODY = 10 MiB` -> `BadResponseError` if exceeded; `except (ValueError, RecursionError)` around `json.loads`.

#### **Observations:**

* **Secrets: clean.** No token or credential in the working tree or in any commit (`git log -p --all` scanned for `FREELANCER_TOKEN=` assignments and long opaque strings; only commit hashes and example slugs). `.env*` is ignored. `keywords.txt` was committed once and later removed; it holds only search terms.
* **Examples and tests are synthetic:** made-up ids (`40000001-3`), `meric@example.com`; no real project, user or client data.
* **Verified good:** GET-only enforced before a request is built; redirects become errors (`_NoRedirect`); TLS verified (urllib default context); token validated (`check_token`) so no header injection; token masked before truncation in traces and in CLI errors; query params URL-encoded (`quote_via=quote`); project id `[0-9]{1,12}`, ASCII only; `ensure_config` uses `open("x")` so it never follows a planted symlink; `Retry-After` capped and NaN/inf-safe; `--json` uses `ensure_ascii=True`.
* **CI hardening:** `permissions: contents: read` and `pull_request` (not `pull_request_target`) are right. Actions are pinned to tags (`@v4`, `@v5`); pinning to commit SHAs guards against a hijacked tag.
* **Traces grow forever** and record every search query. Not secret, but a retention cap (e.g. delete files older than 30 days) or a README note keeps the history bounded.
* **`seen.json.tmp` has a fixed name:** two concurrent `scan --only-new` runs race (last writer wins). Harmless; `tempfile.NamedTemporaryFile(dir=config, delete=False)` would fix it together with the symlink item above.
* **Proxy env vars** (`https_proxy`) are honoured by urllib; the token then travels inside the proxy's CONNECT tunnel, still under TLS. Fine, worth one README line.
