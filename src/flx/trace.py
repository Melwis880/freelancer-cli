"""Always-on JSONL trace: one line per step, linked by `run_id` + `seq`.

Lines go to `traces/YYYY-MM-DD.jsonl` (local date) and, with --debug, to stderr as well. Registered
secrets are masked in every string and long strings are shortened, so neither the token nor full
project descriptions ever land on disk. Lines are pure ASCII (non-ASCII is escaped), so API text in
a trace cannot reach the terminal as a control, bidi or zero-width character, with --debug or `cat`.
"""

from __future__ import annotations

import json
import sys
import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

from flx.auth import redact

MAX_STR = 200


class Tracer:
    def __init__(
        self,
        command: str,
        trace_dir: Path,
        *,
        debug: bool = False,
        stream: TextIO | None = None,
        now: Callable[[], datetime] | None = None,
    ):
        self.run_id = uuid.uuid4().hex[:12]
        self.command = command
        self.trace_dir = Path(trace_dir)
        self.debug = debug
        self._stream = stream  # None means sys.stderr at the time of writing
        self._now = now or (lambda: datetime.now().astimezone())
        self._seq = 0
        self._secrets: list[str] = []
        self._write_failed = False

    def add_secret(self, secret: str) -> None:
        if secret and secret not in self._secrets:
            self._secrets.append(secret)

    def scrub(self, text: str) -> str:
        return redact(text, self._secrets)

    def log(self, step: str, **fields: Any) -> dict:
        self._seq += 1
        now = self._now()
        record = self._clean(
            {
                "run_id": self.run_id,
                "seq": self._seq,
                "ts": now.isoformat(timespec="milliseconds"),
                "command": self.command,
                "step": step,
                **fields,
            }
        )
        line = json.dumps(record)
        self._write(self.trace_dir / f"{now:%Y-%m-%d}.jsonl", line)
        if self.debug:
            print(line, file=self._stream or sys.stderr)
        return record

    def _clean(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {str(k): self._clean(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._clean(v) for v in value]
        if value is None or isinstance(value, (bool, int, float)):
            return value
        text = self.scrub(str(value))  # mask before shortening so no token prefix survives
        return text if len(text) <= MAX_STR else text[:MAX_STR] + "..."

    def _write(self, path: Path, line: str) -> None:
        if self._write_failed:
            return
        try:
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError as exc:
            self._write_failed = True
            print(
                f"flx: could not write trace to {path.parent} ({exc.strerror or exc}); "
                "continuing without it.",
                file=self._stream or sys.stderr,
            )
