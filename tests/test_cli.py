import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch

from clipear.cli import main
from clipear.config import Settings


class CLITests(unittest.TestCase):
    def test_help_and_machine_readable_doctor(self):
        with tempfile.TemporaryDirectory() as directory:
            out = io.StringIO()
            with redirect_stdout(out):
                code = main(["--home", directory, "doctor"])
            self.assertEqual(code, 0)
            self.assertIn("tools", json.loads(out.getvalue()))

    def test_approval_cannot_be_piped_or_given_a_yes_flag(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("sys.stdin", io.StringIO("APPROVE anything\n")), redirect_stderr(io.StringIO()):
                self.assertNotEqual(main(["--home", directory, "approve", "a" * 32]), 0)
            with self.assertRaises(SystemExit) as rejected, redirect_stderr(io.StringIO()):
                main(["--home", directory, "approve", "a" * 32, "--yes"])
            self.assertEqual(rejected.exception.code, 2)

    def test_nonexistent_source_is_a_clear_error(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stderr(io.StringIO()) as err:
            self.assertEqual(main(["--home", directory, "import", str(Path(directory) / "missing.mp4")]), 1)
            self.assertIn("error", err.getvalue().lower())


if __name__ == "__main__":
    unittest.main()
