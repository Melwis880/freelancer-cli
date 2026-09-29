# CLAUDE.md

## Must-follow constraints
- Read-only tool: the HTTP client must only send GET. Never add POST/PUT/PATCH/DELETE or any bid/message feature.
- Python stdlib only. Do not add dependencies (no requests, no freelancersdk).
- Never print, log, or trace `FREELANCER_TOKEN`; mask it in errors. It loads from env var, then `./.env.local`, then `~/.config/flx/.env.local`.
- Architecture and security choices live in `DECISIONS.md`. Do not change one silently; ask Meriç first.
- CLI returns data only; no filtering or scoring (that belongs to the proposal agent).

## Validation before finishing
- `python -m unittest discover -s tests` must pass in full after every change (regression guard).
- New behaviour needs a scenario in `tests/SCENARIOS.md` and a test for it.

## Repo-specific conventions
- API base `https://www.freelancer.com/api`, auth header `Freelancer-OAuth-V1`.
- Planned-but-unbuilt features are `NotImplementedError` stubs (e.g. `flx login`); never fake them.
- `--debug` mirrors trace lines to stderr (token masked).
- JSON output carries `schema_version`; bump it on any field change.
- Files live in `$XDG_CONFIG_HOME/flx` (default `~/.config/flx`, created on first run): `.env.local`, `keywords.txt`, `seen.json` (IDs only, backs `--only-new`), `traces/YYYY-MM-DD.jsonl` (always on, linked by `run_id` + `seq`). `.env.local`/`keywords.txt` in cwd override. Tests must set `XDG_CONFIG_HOME` to a temp dir (see `tests/fakes.run_cli`).
- 429: exponential backoff, max 3 retries (1/2/4 s, honour `Retry-After` up to 10 s). Timeout: one retry after 2 s. `scan` spaces keyword requests >= 1 s start to start.
- Read `PROGRESS.md` at session start; tick finished tasks at the end. PROGRESS/DECISIONS are Turkish, code/README English.

## Change safety rules
- Never add a git remote or push without Meriç's fresh "yes".
