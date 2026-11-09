from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from pydantic import TypeAdapter

from .models import Resume


class ResumeSection(StrEnum):
    TECHNOLOGIES = "technologies"
    SKILLS = "skills"
    RESPONSIBILITIES = "responsibilities"
    POSITIONS = "positions"
    CHECKLIST = "checklist"
    EDUCATION = "education"
    LANGUAGES = "languages"
    AWARDS = "awards"
    PROJECTS = "projects"
    CONTACT = "contact"


RESUME_SECTIONS: Mapping[ResumeSection, TypeAdapter[object]] = MappingProxyType(
    {
        ResumeSection(name): TypeAdapter(field.rebuild_annotation())
        for name, field in Resume.model_fields.items()
    }
)


def section_schema(section: ResumeSection | str) -> dict[str, Any]:
    return RESUME_SECTIONS[ResumeSection(section)].json_schema()


def validate_section(section: ResumeSection | str, value: object) -> object:
    return RESUME_SECTIONS[ResumeSection(section)].validate_python(value, strict=True)
