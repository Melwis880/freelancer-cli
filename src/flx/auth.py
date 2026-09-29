"""Authentication helpers.

`login` is a placeholder for a one-time OAuth flow (`flx login`). It stays unimplemented until we
know the Freelancer developer panel cannot hand out a token directly (PROGRESS.md, Phase 3).
"""


def login() -> None:
    raise NotImplementedError(
        "flx login is not built yet. Put FREELANCER_TOKEN in .env.local instead."
    )
