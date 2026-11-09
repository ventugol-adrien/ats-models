import json
import sqlite3
import unittest
from pathlib import Path

from ats_models import (
    ApplicationRow,
    JobRow,
    ResumeRow,
    application_from_row,
    job_from_row,
    job_to_row,
    resume_from_row,
    resume_to_row,
)


class DatabaseContractTests(unittest.TestCase):
    def setUp(self) -> None:
        source = Path(__file__).resolve().parents[3] / "job-app-db/src/job_app_db/schema.sql"
        if not source.is_file():
            self.skipTest("job-app-db SQL source is not present in this checkout")
        schema = source.read_text(encoding="utf-8")
        self.connection = sqlite3.connect(":memory:")
        self.addCleanup(self.connection.close)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(schema)

    def test_row_fields_match_authoritative_tables_and_view(self) -> None:
        for name, model in (
            ("jobs", JobRow), ("resumes", ResumeRow), ("applications", ApplicationRow)
        ):
            with self.subTest(name=name):
                columns = self.connection.execute(f"PRAGMA table_info({name})").fetchall()
                self.assertEqual(
                    [column["name"] for column in columns], list(model.model_fields)
                )
                for column in columns:
                    if column["notnull"] == 0 and name != "applications":
                        self.assertIn(
                            {"type": "null"},
                            model.model_json_schema()["properties"][column["name"]]["anyOf"],
                        )
        for name in ("jobs", "resumes"):
            column = "keywords" if name == "jobs" else "skills"
            with self.subTest(name=name), self.assertRaises(sqlite3.DatabaseError):
                self.connection.execute(
                    f"INSERT INTO {name} (id, {column}) VALUES ('invalid', 'not JSON')"
                )

    def insert_payload(self, table: str, payload: dict[str, object]) -> None:
        model = JobRow if table == "jobs" else ResumeRow
        fields = list(model.model_fields)
        values = [
            self.connection.execute(
                "SELECT json_extract(?, ?)", (json.dumps(payload), f"$.{field}")
            ).fetchone()[0]
            for field in fields
        ]
        placeholders = ", ".join("?" for _ in fields)
        self.connection.execute(
            f"INSERT INTO {table} ({', '.join(fields)}) VALUES ({placeholders})",
            values,
        )

    def test_sqlite_rows_round_trip_without_writing(self) -> None:
        for table, payload, read, write in (
            ("jobs", {"id": "job-1", "link": "", "keywords": {}},
             job_from_row, job_to_row),
            ("resumes", {
                "id": "resume-1", "job": "job-1", "skills": ["Python"],
                "awards": [["Example", "Details"]], "successful": True,
                "basis_for_resumes": ["resume-2"],
            }, resume_from_row, resume_to_row),
        ):
            self.insert_payload(table, payload)
            source = dict(self.connection.execute(f"SELECT * FROM {table}").fetchone())
            row = (JobRow if table == "jobs" else ResumeRow).model_validate(source)
            record = read(row)
            self.assertEqual(write(record, original=row).model_dump(), source)

    def test_view_uses_resume_job_not_jobs_resume(self) -> None:
        self.insert_payload("jobs", {"id": "job-1", "resume": "different-resume"})
        self.insert_payload("jobs", {"id": "job-2", "resume": "resume-1"})
        self.insert_payload(
            "resumes", {"id": "resume-1", "job": "job-1", "successful": False}
        )
        self.insert_payload(
            "resumes", {"id": "resume-2", "job": "missing-job", "successful": None}
        )
        results = self.connection.execute("SELECT * FROM applications").fetchall()
        self.assertEqual(len(results), 1)
        application = application_from_row(dict(results[0]))
        self.assertEqual(application.job_id, "job-1")
        self.assertEqual(application.resume_id, "resume-1")
        self.assertEqual(application.successful, 0)
        self.assertEqual(application.resume_item.successful, 0)


if __name__ == "__main__":
    unittest.main()
