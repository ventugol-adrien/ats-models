import io
import json
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from ats_models import JobRecord, job_to_row
from ats_models.cli import main


class CLITests(unittest.TestCase):
    def run_cli(self, argv: list[str], data: str = "") -> tuple[int, str, str]:
        output, error = io.StringIO(), io.StringIO()
        with (
            patch("sys.stdin", io.StringIO(data)),
            redirect_stdout(output),
            redirect_stderr(error),
        ):
            status = main(argv)
        return status, output.getvalue(), error.getvalue()

    def test_validate_preserves_omission_and_custom_fields(self) -> None:
        data = {"id": "job-1", "keywords": None, "custom": {"kept": True}}
        status, output, error = self.run_cli(
            ["validate", "job-record"], json.dumps(data)
        )
        self.assertEqual(status, 0, error)
        self.assertEqual(json.loads(output), data)
        self.assertEqual(error, "")

    def test_jsonl_is_explicit_and_atomic_on_validation_failure(self) -> None:
        data = '{"id": "one"}\n{"id": "two"}\n'
        status, output, error = self.run_cli(
            ["validate", "job-record", "--jsonl"], data
        )
        self.assertEqual(status, 0, error)
        self.assertEqual(len(output.splitlines()), 2)
        status, output, error = self.run_cli(["validate", "job-record"], data)
        self.assertEqual(status, 2)
        self.assertEqual(output, "")
        status, output, error = self.run_cli(
            ["validate", "job-record", "--jsonl"],
            '{"id": "one"}\n{"id": 2}\n',
        )
        self.assertEqual(status, 2)
        self.assertEqual(output, "")
        self.assertIn("line 2", error)
        self.assertIn("id", error)

    def test_source_modes_are_explicit(self) -> None:
        row = job_to_row(JobRecord(id="job-1", title="Example"))
        status, output, error = self.run_cli(
            ["validate", "job-record", "--source", "row"], row.model_dump_json()
        )
        self.assertEqual(status, 0, error)
        self.assertEqual(json.loads(output), {"id": "job-1", "title": "Example"})
        status, output, error = self.run_cli(
            ["validate", "job-input", "--source", "utility"],
            '{"job_url": "", "description": "Example"}',
        )
        self.assertEqual(status, 0, error)
        self.assertEqual(
            json.loads(output), {"link": "", "description": "Example"}
        )
        for argv in (
            ["validate", "resume", "--source", "utility"],
            ["validate", "job-input", "--source", "row"],
        ):
            with self.subTest(argv=argv):
                status, output, error = self.run_cli(argv, "{}")
                self.assertEqual(status, 2)
                self.assertEqual(output, "")
                self.assertIn("--source", error)

    def test_schema_model_and_section(self) -> None:
        for argv in (["schema", "resume"], ["schema", "--section", "positions"]):
            with self.subTest(argv=argv):
                status, output, error = self.run_cli(argv)
                self.assertEqual(status, 0, error)
                value = json.loads(output)
                self.assertIn("$defs", value)
        _, output, _ = self.run_cli(["schema", "job-row"])
        self.assertNotIn("item_json", json.loads(output)["properties"])

    def test_invalid_json_and_nested_data_report_paths(self) -> None:
        for data in ("", "[]", "not JSON", '{"positions": [{"title": 1}]}'):
            with self.subTest(data=data):
                status, output, error = self.run_cli(["validate", "resume-draft"], data)
                self.assertEqual(status, 2)
                self.assertEqual(output, "")
                self.assertTrue(error)
                if "positions" in data:
                    self.assertIn("positions.0.title", error)

    def test_file_input_and_io_errors(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "job.json"
            path.write_text('{"link": ""}', encoding="utf-8")
            status, output, error = self.run_cli(
                ["validate", "job-record", str(path)]
            )
            self.assertEqual(status, 0, error)
            self.assertEqual(json.loads(output), {"link": ""})
            status, output, error = self.run_cli(
                ["validate", "job-record", str(path.with_name("missing.json"))]
            )
            self.assertEqual(status, 1)
            self.assertEqual(output, "")
            self.assertTrue(error)

    def test_missing_input_does_not_block_on_tty(self) -> None:
        with (
            patch("sys.stdin.isatty", return_value=True),
            patch("sys.stdin.read") as read,
            redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(main(["validate", "job-record"]), 2)
        read.assert_not_called()

    def test_installed_entry_point(self) -> None:
        executable = Path(sys.executable).with_name("ats-models")
        result = subprocess.run(
            [str(executable), "validate", "job-record"],
            input='{"id": "job-1"}',
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"id": "job-1"})
        self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
