"""Token loading and masking, plus the `flx login` placeholder.

The token comes from the FREELANCER_TOKEN environment variable, else from `.env.local` in the
current directory, else from `.env.local` in the config dir (see files.py). It must never be
printed, logged or traced; `redact` masks it wherever text leaves flx.

`login` is a placeholder for a one-time OAuth flow (`flx login`). It stays unimplemented until we
know the Freelancer developer panel cannot hand out a token directly (PROGRESS.md, Phase 3).
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from pathlib import Path

from flx.errors import TokenError
from flx.files import read_small, reason

TOKEN_ENV = "FREELANCER_TOKEN"
ENV_FILE = ".env.local"
MASK = "***"


def load_token(cwd: Path, config: Path, environ: Mapping[str, str] | None = None) -> str:
    """Return the token from the environment, else `cwd/.env.local`, else `config/.env.local`."""
    environ = os.environ if environ is None else environ
    token = environ.get(TOKEN_ENV, "").strip()
    for path in (Path(cwd) / ENV_FILE, Path(config) / ENV_FILE):
        token = token or _token_from_file(path)
    if not token:
        raise _missing(Path(config) / ENV_FILE)
    return token


def check_token(token: str) -> None:
    """Refuse a token that is empty or would break the HTTP header. Never echoes the token."""
    if not token:
        raise _missing()
    if not (token.isascii() and token.isprintable()) or " " in token:
        raise TokenError(
            f"{TOKEN_ENV} contains spaces, line breaks or non-ASCII characters; copy it again."
        )


def redact(text: str, secrets: Iterable[str]) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, MASK)
    return text


def _missing(env_file: Path | str = ENV_FILE) -> TokenError:
    return TokenError(f"No Freelancer token found. Set {TOKEN_ENV}, or put {TOKEN_ENV}=... in {env_file}.")


def _token_from_file(path: Path) -> str:
    try:
        text = read_small(path)
    except FileNotFoundError:
        return ""
    except (OSError, ValueError) as exc:
        raise TokenError(f"Could not read {path} ({reason(exc)}).") from None
    token = ""
    for line in text.splitlines():
        key, sep, value = line.strip().removeprefix("export ").partition("=")
        if sep and key.strip() == TOKEN_ENV:
            token = _unquote(value.strip())  # last assignment wins, as in a shell
    return token


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value


def login() -> None:
    raise NotImplementedError(
        "flx login is not built yet. Put FREELANCER_TOKEN in .env.local instead."
    )
