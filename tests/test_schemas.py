import unittest

from jsonschema import Draft202012Validator
from pydantic import ValidationError

from ats_models import (
    RESUME_SECTIONS,
    Contribution,
    Resume,
    ResumeSection,
    section_schema,
    validate_section,
)


class SchemaTests(unittest.TestCase):
    def test_registry_matches_resume_fields(self) -> None:
        self.assertEqual(set(RESUME_SECTIONS), set(Resume.model_fields))
        self.assertEqual(set(ResumeSection), set(Resume.model_fields))

    def test_schemas_and_validators_agree_for_each_section(self) -> None:
        examples = {
            "technologies": ({"cloud": ["AWS"]}, {"cloud": [1]}),
            "skills": ([["Python"]], ["Python"]),
            "responsibilities": ("Build services", []),
            "positions": (
                [{"company": "Example", "title": "Developer", "dates": "2021-present",
                  "responsibilities": "Build services", "contributions": []}],
                [{"title": "Developer"}],
            ),
            "checklist": (["x" * 100], [1]),
            "education": ({"qualification": "Example"}, {"qualification": []}),
            "languages": (
                [{"language": "Italian", "level": "B2", "note": "Professional"}],
                [{"language": "Italian", "level": "D1"}],
            ),
            "awards": (
                [{"title": "Example", "description": "Details"}],
                [["Example", "Details"]],
            ),
            "projects": (
                [{"headline": "Example", "link": "https://example.com/project"}],
                [{"headline": "Example", "link": "ftp://example.com/project"}],
            ),
            "contact": ({"email": "example@example.com"}, {"email": 1}),
        }
        for section, (valid, invalid) in examples.items():
            with self.subTest(section=section):
                schema = section_schema(section)
                Draft202012Validator.check_schema(schema)
                validator = Draft202012Validator(schema)
                validator.validate(valid)
                validate_section(section, valid)
                self.assertFalse(validator.is_valid(invalid))
                with self.assertRaises(ValidationError):
                    validate_section(section, invalid)

    def test_nested_refs_resolve_and_schema_results_are_independent(self) -> None:
        schema = section_schema("positions")
        self.assertIn("Contribution", schema["$defs"])
        self.assertIn("headline", schema["$defs"]["Contribution"]["required"])
        schema["$defs"]["Contribution"]["required"].clear()
        fresh = section_schema("positions")
        self.assertEqual(
            fresh["$defs"]["Contribution"]["required"],
            Contribution.model_json_schema()["required"],
        )

    def test_unknown_sections_fail_explicitly(self) -> None:
        for helper in (section_schema, validate_section):
            with self.subTest(helper=helper.__name__), self.assertRaises(ValueError):
                if helper is section_schema:
                    helper("unknown")
                else:
                    helper("unknown", [])


if __name__ == "__main__":
    unittest.main()
