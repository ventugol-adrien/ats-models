import copy
import json
import unittest

from pydantic import ValidationError

from ats_models import (
    ApplicationRow,
    JobRecord,
    JobRow,
    ResumeRecord,
    ResumeRow,
    adapt_job_fields,
    application_from_row,
    job_from_row,
    job_to_row,
    parse_json_object,
    parse_resume_payload,
    record_to_payload,
    resume_from_row,
    resume_to_row,
    successful_as_bool,
)


def make_resume_row() -> ResumeRow:
    payload = {
        "id": "resume-1",
        "job": "job-1",
        "skills": ["Python", "Collaboration"],
        "awards": [["Example", "Details"]],
        "positions": [{"title": "Developer"}],
        "basis_for_resumes": ["resume-2"],
        "successful": False,
    }
    return resume_to_row(
        ResumeRecord.model_validate(
            {**payload, "skills": [["Python", "Collaboration"]],
             "awards": [{"title": "Example", "description": "Details"}]}
        )
    ).model_copy(
        update={
            "skills": '[ "Python", "Collaboration" ]',
            "awards": '[["Example", "Details"]]',
        }
    )


class CompatibilityTests(unittest.TestCase):
    def test_explicit_job_name_adaptation(self) -> None:
        data = {
            "job_url": "",
            "created_at": "not a parsed date",
            "updated_at": None,
            "location": "Remote",
            "company_domain": "example.com",
            "custom": {"kept": True},
        }
        original = copy.deepcopy(data)
        adapted = adapt_job_fields(data)
        self.assertEqual(data, original)
        self.assertEqual(adapted["link"], "")
        self.assertEqual(adapted["entry_date"], "not a parsed date")
        self.assertIsNone(adapted["modified_date"])
        self.assertEqual(adapted["location"], "Remote")
        self.assertNotIn("job_url", adapted)

    def test_adaptation_reports_alias_conflicts_and_request_flags(self) -> None:
        for data in (
            {"link": "a", "job_url": "b"},
            {"entry_date": None, "created_at": ""},
            {"modified_date": "a", "updated_at": "b"},
            {"description": "Example", "db_insert": False},
        ):
            with self.subTest(data=data), self.assertRaises(ValueError):
                adapt_job_fields(data)
        self.assertEqual(
            adapt_job_fields({"link": "", "job_url": ""}), {"link": ""}
        )

    def test_json_root_and_nonfinite_numbers(self) -> None:
        for value in ("[]", "null", "1", '"text"', "{}", "not JSON"):
            if value == "{}":
                self.assertEqual(parse_json_object(value), {})
            else:
                with self.subTest(value=value), self.assertRaises(ValueError):
                    parse_json_object(value)
        for value in ('{"extra": NaN}', '{"extra": Infinity}'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_json_object(value)
        self.assertEqual(parse_json_object(b'{"id": null}'), {"id": None})

    def test_legacy_sections_are_normalized_without_mutation(self) -> None:
        original = {"skills": ["Python"], "awards": [["Example", "Details"]]}
        before = copy.deepcopy(original)
        record = parse_resume_payload(original)
        self.assertEqual(record.skills, [["Python"]])
        self.assertEqual(record.awards[0].title, "Example")
        self.assertEqual(original, before)
        self.assertEqual(record_to_payload(record, original=original), before)
        self.assertEqual(
            record_to_payload(record)["awards"],
            [{"title": "Example", "description": "Details"}],
        )

    def test_invalid_legacy_sections_are_not_repaired(self) -> None:
        for data in (
            {"skills": ["Python", ["Collaboration"]]},
            {"skills": [1]},
            {"awards": [["Example"]]},
            {"awards": [["Example", 3]]},
            {"awards": [["Example", "Details", "Extra"]]},
        ):
            with self.subTest(data=data), self.assertRaises(ValueError):
                parse_resume_payload(data)

    def test_nullable_keywords_and_empty_values_are_not_filled(self) -> None:
        for data in ({}, {"keywords": None}, {"keywords": {}}, {"link": ""}):
            with self.subTest(data=data):
                record = JobRecord.model_validate(data)
                self.assertEqual(record_to_payload(record), data)

    def test_resume_row_round_trip_retains_exact_legacy_strings(self) -> None:
        source = make_resume_row()
        record = resume_from_row(source)
        self.assertEqual(record.skills, [["Python", "Collaboration"]])
        self.assertEqual(record.basis_for_resumes, ["resume-2"])
        self.assertEqual(record.successful, 0)
        restored = resume_to_row(record, original=source)
        self.assertEqual(restored, source)
        self.assertEqual(restored.skills, '[ "Python", "Collaboration" ]')

    def test_changed_field_preserves_unrelated_encodings(self) -> None:
        source = make_resume_row()
        record = resume_from_row(source)
        record.responsibilities = ""
        updated = resume_to_row(record, original=source)
        self.assertEqual(updated.skills, source.skills)
        self.assertEqual(updated.awards, source.awards)
        self.assertEqual(updated.responsibilities, "")

    def test_changed_section_uses_shared_shape(self) -> None:
        source = make_resume_row()
        record = resume_from_row(source)
        record.skills = [["Go"]]
        updated = resume_to_row(record, original=source)
        self.assertEqual(json.loads(updated.skills), [["Go"]])
        self.assertEqual(updated.awards, source.awards)

    def test_nested_default_edits_are_not_lost(self) -> None:
        source = resume_to_row(ResumeRecord(technologies={}, positions=[{}]))
        record = resume_from_row(source)
        record.technologies.backend.append("Python")
        record.positions[0].index = 1
        updated = resume_to_row(record, original=source)
        self.assertEqual(json.loads(updated.technologies), {"backend": ["Python"]})
        self.assertEqual(json.loads(updated.positions), [{"index": 1}])
        self.assertIsNone(updated.contact)

    def test_explicit_boolean_integer_change_is_not_discarded(self) -> None:
        source = make_resume_row()
        record = resume_from_row(source)
        record.successful = 0
        updated = resume_to_row(record, original=source)
        self.assertIs(type(updated.successful), int)

    def test_nested_json_uses_the_sql_column_as_authority(self) -> None:
        source = resume_to_row(
            ResumeRecord(basis_for_resumes=[False])
        ).model_copy(
            update={"basis_for_resumes": "[0]"}
        )
        self.assertEqual(resume_from_row(source).basis_for_resumes, [0])

    def test_job_row_round_trip_preserves_nulls_blank_ids_and_dates(self) -> None:
        for payload in (
            {},
            {"id": None, "entry_date": "", "link": "", "keywords": None},
            {"id": "", "keywords": {}},
            {"id": "job-1", "entry_date": "2026-01-01", "resume": "other-resume"},
        ):
            with self.subTest(payload=payload):
                record = JobRecord.model_validate(payload)
                source = job_to_row(record)
                restored = job_from_row(source)
                self.assertEqual(restored.model_dump(), record.model_dump())
                self.assertEqual(job_to_row(restored, original=source), source)

    def test_invalid_json_and_nested_shapes_are_reported(self) -> None:
        source = make_resume_row()
        for update, message in (
            ({"skills": "not JSON"}, "skills"),
            ({"skills": "[1]"}, "skills"),
        ):
            with self.subTest(update=update), self.assertRaisesRegex(ValueError, message):
                resume_from_row(source.model_copy(update=update))

    def test_sql_metadata_is_authoritative(self) -> None:
        source = job_to_row(JobRecord(
            id="job-1", entry_date="2026-01-01", modified_date="2026-02-01", link=""
        ))
        record = job_from_row(source)
        self.assertEqual(record.id, "job-1")
        self.assertEqual(record.entry_date, "2026-01-01")
        self.assertEqual(record.modified_date, "2026-02-01")
        self.assertEqual(job_to_row(record, original=source), source)

    def test_sql_null_metadata_is_preserved(self) -> None:
        source = job_to_row(JobRecord())
        record = job_from_row(source)
        self.assertIsNone(record.id)
        self.assertIsNone(record.entry_date)
        self.assertEqual(job_to_row(record, original=source), source)

    def test_resume_sql_metadata_is_authoritative(self) -> None:
        source = make_resume_row().model_copy(update={
            "id": "new-id", "modified_date": "new-date", "successful": 1,
        })
        record = resume_from_row(source)
        self.assertEqual(record.id, "new-id")
        self.assertEqual(record.modified_date, "new-date")
        self.assertEqual(record.successful, 1)
        self.assertEqual(resume_to_row(record, original=source), source)

    def test_new_rows_store_metadata_only_in_sql_columns(self) -> None:
        for record, write, read in (
            (JobRecord(id="job-1", entry_date="date"), job_to_row, job_from_row),
            (ResumeRecord(id="resume-1", successful=False), resume_to_row, resume_from_row),
        ):
            with self.subTest(record=record):
                row = write(record)
                self.assertNotIn("item_json", row.model_dump())
                restored = read(row)
                self.assertEqual(restored.id, record.id)
                self.assertEqual(write(restored, original=row), row)

    def test_metadata_edits_do_not_add_metadata_to_content_json(self) -> None:
        source = job_to_row(JobRecord(id="job-1", title="Developer"))
        record = job_from_row(source)
        record.modified_date = "new-date"
        record.title = "Senior developer"
        updated = job_to_row(record, original=source)
        self.assertEqual(updated.modified_date, "new-date")
        self.assertEqual(updated.title, "Senior developer")
        self.assertNotIn("item_json", updated.model_dump())

    def test_fields_without_sql_columns_are_rejected(self) -> None:
        for record, write in (
            (JobRecord(id="job-1", successful={"custom": True}), job_to_row),
            (ResumeRecord(custom={"kept": True}), resume_to_row),
        ):
            with self.subTest(record=record), self.assertRaisesRegex(ValueError, "SQL columns"):
                write(record)

    def test_rows_require_all_sql_columns_and_valid_object_json(self) -> None:
        with self.assertRaises(ValidationError):
            JobRow.model_validate({"id": "job-1"})
        source = job_to_row(JobRecord())
        for value in ('{"extra": NaN}', "not JSON"):
            data = {**source.model_dump(), "keywords": value}
            with self.subTest(value=value), self.assertRaises(ValidationError):
                JobRow.model_validate(data)
        with self.assertRaises(ValidationError):
            JobRow.model_validate({**source.model_dump(), "new_column": ""})

    def test_application_view_parsing_and_conflicts(self) -> None:
        source = make_resume_row()
        row = ApplicationRow(
            successful=0,
            job_id="job-1",
            resume_id="resume-1",
            job_item='{"id": "job-1", "resume": "a-different-resume"}',
            resume_item=json.dumps(record_to_payload(resume_from_row(source))),
        )
        application = application_from_row(row)
        self.assertEqual(application.job_item.resume, "a-different-resume")
        self.assertEqual(application.resume_item.skills, [["Python", "Collaboration"]])
        self.assertEqual(application.successful, 0)
        updated = application_from_row(row.model_copy(update={
            "resume_id": "new-resume", "successful": 1,
        }))
        self.assertEqual(updated.resume_item.id, "new-resume")
        self.assertEqual(updated.resume_item.successful, 1)
        with self.assertRaisesRegex(ValueError, "job"):
            application_from_row(row.model_copy(update={"job_id": "other"}))

    def test_application_view_items_need_no_metadata_copies(self) -> None:
        application = application_from_row(ApplicationRow(
            successful=0,
            job_id="job-1",
            resume_id="resume-1",
            job_item='{"title": "Developer"}',
            resume_item='{"skills": [["Python"]]}',
        ))
        self.assertEqual(application.job_item.id, "job-1")
        self.assertEqual(application.resume_item.id, "resume-1")
        self.assertEqual(application.resume_item.successful, 0)

    def test_boolean_conversion_is_opt_in(self) -> None:
        for value, expected in (
            (None, None), (0, False), (1, True), (False, False), (True, True)
        ):
            with self.subTest(value=value):
                self.assertIs(successful_as_bool(value), expected)
        with self.assertRaises(ValueError):
            successful_as_bool(7)


if __name__ == "__main__":
    unittest.main()
