"""Infrastructure CLI tests: output allocation, not SCRUM-173 acceptance cases.

Exercise main's real parser/startup with child commands stubbed: a bare command
must allocate unique retained evidence, while explicit destinations stay exact
and existing output is never overwritten. No application services are launched.
"""
import contextlib
import verify_scrum173 as runner
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

class VerificationCliTests(unittest.TestCase):
    def invoke(self, *arguments):
        output = io.StringIO()
        with patch("sys.argv", [str(Path(runner.__file__)), *arguments]), patch.object(
            runner.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)
        ), contextlib.redirect_stdout(output):
            self.assertFalse(runner.main())
        return json.loads(output.getvalue().splitlines()[-1])["evidence"]

    def test_omitted_destination_is_unique_absolute_and_retained(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"TMPDIR": directory}), patch.object(tempfile, "tempdir", None):
            first = Path(self.invoke("--integration-only"))
            second = Path(self.invoke("--integration-only"))
            self.assertNotEqual(first, second)
            for destination in (first, second):
                self.assertTrue(destination.is_absolute())
                self.assertEqual(destination.parent, Path(directory).resolve())
                self.assertTrue((destination / "commands.json").is_file())

    def test_explicit_destination_is_preserved_and_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "chosen-output"
            self.assertEqual(self.invoke("--integration-only", "--evidence", str(destination)), str(destination.resolve()))
            with self.assertRaises(FileExistsError):
                self.invoke("--integration-only", "--evidence", str(destination))

    def test_unknown_option_still_fails_parser(self):
        with patch("sys.argv", [str(Path(runner.__file__)), "--not-a-real-option"]), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as result:
                runner.main()
        self.assertEqual(result.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
