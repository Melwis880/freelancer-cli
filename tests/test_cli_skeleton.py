import contextlib
import io
import subprocess
import sys
import unittest
from pathlib import Path

import _path  # noqa: F401

from flx import auth, cli

ROOT = Path(__file__).resolve().parents[1]


class CliSkeletonTest(unittest.TestCase):
    def test_help_lists_every_subcommand(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as ctx:
            cli.main(["--help"])
        self.assertEqual(ctx.exception.code, 0)
        for command in ("whoami", "search", "project", "scan"):
            self.assertIn(command, out.getvalue())

    def test_missing_command_is_an_error(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as ctx:
            cli.main([])
        self.assertNotEqual(ctx.exception.code, 0)

    def test_login_is_a_placeholder(self):
        with self.assertRaises(NotImplementedError):
            auth.login()

    def test_python_dash_m_flx_help_runs(self):
        result = subprocess.run(
            [sys.executable, "-m", "flx", "--help"],
            cwd=ROOT,
            env={"PYTHONPATH": str(ROOT / "src")},
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("scan", result.stdout)


if __name__ == "__main__":
    unittest.main()
