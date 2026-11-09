import json
import subprocess
import sys
import unittest

from pydantic import ValidationError

from ats_models import (
    Application,
    Award,
    Contact,
    Education,
    Job,
    JobKeywords,
    JobRecord,
    Language,
    Position,
    Project,
    Resume,
    ResumeDraft,
    ResumeRecord,
    Technologies,
)


class ModelTests(unittest.TestCase):
    def test_job_content_and_storage_have_different_requiredness(self) -> None:
        with self.assertRaises(ValidationError):
            Job()
        for data in ({}, {"id": None}, {"id": "", "title": None}, {"link": ""}):
            with self.subTest(data=data):
                record = JobRecord.model_validate(data)
                self.assertEqual(
                    record.model_dump(mode="json", exclude_unset=True), data
                )
        self.assertEqual(
            Job(company="", title="", description="").description, ""
        )

    def test_no_personal_defaults(self) -> None:
        resume = Resume(
            technologies=Technologies(),
            skills=[],
            positions=[],
            awards=[],
            projects=[],
        )
        self.assertEqual(resume.languages, [])
        self.assertEqual(resume.technologies.frontend, [])
        self.assertEqual(resume.contact, Contact())
        self.assertIsNone(resume.contact.email)
        self.assertIsNone(resume.education.qualification)
        self.assertIsNone(Education().institution)
        with self.assertRaises(ValidationError):
            Position(responsibilities="Build services")

    def test_independent_mutable_defaults(self) -> None:
        first, second = JobKeywords(), JobKeywords()
        first.technologies.append("Python")
        self.assertEqual(second.technologies, [])
        first_tech, second_tech = Technologies(), Technologies()
        first_tech.cloud.append("AWS")
        self.assertEqual(second_tech.cloud, [])

    def test_draft_nested_values_are_typed_and_omissible(self) -> None:
        data = {
            "positions": [{"title": "Developer", "custom": ["preserved"]}],
            "languages": [{}],
            "projects": [{}],
            "awards": [{}],
        }
        draft = ResumeDraft.model_validate(data)
        self.assertEqual(draft.model_dump(mode="json", exclude_unset=True), data)
        for invalid in (
            {"positions": [{"title": 42}]},
            {"skills": ["Python"]},
            {"skills": [["Python", 1]]},
            {"awards": [["Award", "Details"]]},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                ResumeDraft.model_validate(invalid)

    def test_record_nulls_dates_and_opaque_provenance(self) -> None:
        data = {
            "id": "not-a-uuid",
            "entry_date": "2026-01-02T03:04:05",
            "modified_date": "",
            "technologies": None,
            "skills": None,
            "education": None,
            "responsibilities": None,
            "job": "",
            "basis_for_resumes": '["not reinterpreted"]',
            "successful": 7,
        }
        record = ResumeRecord.model_validate(data)
        self.assertEqual(record.model_dump(mode="json", exclude_unset=True), data)

    def test_omission_and_explicit_null_survive_round_trip(self) -> None:
        omitted = ResumeRecord()
        cleared = ResumeRecord(contact=None)
        self.assertEqual(omitted.model_dump(exclude_unset=True), {})
        self.assertEqual(cleared.model_dump(exclude_unset=True), {"contact": None})
        for record in (omitted, cleared):
            restored = ResumeRecord.model_validate_json(
                record.model_dump_json(exclude_unset=True)
            )
            self.assertEqual(restored.model_fields_set, record.model_fields_set)

    def test_custom_json_fields_are_preserved_at_every_level(self) -> None:
        data = {
            "id": "resume-1",
            "custom": {"nested": [True, None, 1, 2.5]},
            "positions": [{"title": "Developer", "custom": "value"}],
            "technologies": {"new_category": ["Example"]},
        }
        record = ResumeRecord.model_validate_json(json.dumps(data))
        self.assertEqual(record.model_dump(mode="json", exclude_unset=True), data)
        with self.assertRaises(ValidationError):
            ResumeRecord.model_validate({"custom": object()})
        with self.assertRaises(ValidationError):
            ResumeRecord.model_validate({"custom": {"value": float("inf")}})

    def test_strict_scalar_types(self) -> None:
        for invalid in (
            {"id": 1},
            {"entry_date": 123},
            {"successful": "false"},
            {"successful": 1.5},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                ResumeRecord.model_validate(invalid)
        for value in (None, False, True, 0, 1, 9):
            record = ResumeRecord(successful=value)
            self.assertEqual(record.successful, value)
            self.assertIs(type(record.successful), type(value))

    def test_general_purpose_components(self) -> None:
        language = Language(language="Italian", level="B2", note="Professional")
        self.assertEqual(language.level, "B2")
        with self.assertRaises(ValidationError):
            Language(language="Italian", level="D1")
        project = Project(headline="Example", link="https://example.com/project")
        self.assertEqual(project.link, "https://example.com/project")
        with self.assertRaises(ValidationError):
            Project(headline="Example", link="ftp://example.com/project")
        with self.assertRaises(ValidationError):
            Project(headline="Example", link="https://example.com:invalid/project")
        self.assertEqual(Award(title="Example", description="Details").title, "Example")

    def test_application_matches_view_not_an_independent_entity(self) -> None:
        data = {
            "successful": None,
            "job_id": "job-1",
            "resume_id": "resume-1",
            "job_item": {"id": "job-1"},
            "resume_item": {"id": "resume-1", "job": "job-1"},
        }
        application = Application.model_validate(data)
        self.assertEqual(
            application.model_dump(mode="json", exclude_unset=True), data
        )
        self.assertEqual(set(Application.model_fields), set(data))

    def test_import_requires_no_provider_renderer_or_database(self) -> None:
        code = """
import sys
import ats_models
for forbidden in ("sqlite3", "fastapi", "google.genai", "pylatex"):
    assert forbidden not in sys.modules, forbidden
assert ats_models.JobKeywords().technologies == []
"""
        result = subprocess.run(
            [sys.executable, "-c", code],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
