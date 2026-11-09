import json
from typing import Annotated, Any, Literal, Self
from urllib.parse import urlsplit

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    TypeAdapter,
    field_validator,
    model_validator,
)

_extras_adapter = TypeAdapter(
    dict[str, JsonValue], config=ConfigDict(strict=True, allow_inf_nan=False)
)


class ContentModel(BaseModel):
    model_config = ConfigDict(
        strict=True, extra="allow", allow_inf_nan=False, validate_assignment=True
    )

    @model_validator(mode="after")
    def validate_json_extras(self) -> Self:
        if self.model_extra:
            _extras_adapter.validate_python(self.model_extra)
        return self


class ResumeSection(ContentModel):
    static: bool = True


class JobKeywords(ContentModel):
    technologies: list[str] = Field(
        default_factory=list,
        description="List of technologies, programming languages and frameworks that the ideal candidate would know.",
    )
    tech_skills: list[str] = Field(
        default_factory=list,
        description="List of technical skills, methodologies and software/AI engineering practices that the ideal candidate would know.",
    )
    soft_skills: list[str] = Field(
        default_factory=list,
        description="List of soft, interpersonal and communication skills that the ideal candidate would possess.",
    )
    qualities: list[str] = Field(
        default_factory=list,
        description="List of personal qualities that the ideal candidate would possess.",
    )


class JobLinks(ContentModel):
    favicon: str | None = None
    link: str | None = None
    keywords: JobKeywords | None = None
    resume: str | None = None


class JobInput(JobLinks):
    company: str | None = None
    title: str | None = None
    description: str | None = None


class Job(JobLinks):
    company: str
    title: str
    description: str


class RecordMetadata(ContentModel):
    id: str | None = None
    entry_date: str | None = None
    modified_date: str | None = None


class JobRecord(JobInput, RecordMetadata):
    """Decoded job payload; absent fields and SQL nulls remain distinct."""


class JobDescriptionInput(BaseModel):
    description: str
    job_url: str
    title: str | None = None
    company: str | None = None
    location: str | None = None
    company_domain: str | None = None
    keywords: JobKeywords | None = None
    db_insert: bool = Field(
        description="Indicates whether the job description should be inserted into the database.",
        default=False,
    )


class JobDescription(BaseModel):
    created_at: str
    updated_at: str
    title: str = Field(description="The title of the job.")
    description: str = Field(description="The full text of the job description.")
    company: str = Field(description="The name of the hiring company.")
    location: str = Field(description="The job's location, including remote status.")
    company_domain: str = Field(
        description="The hiring company's website domain, without a URL scheme."
    )
    favicon: str = Field(description="The URL of the company's favicon.")
    job_url: str = Field(description="The URL of the job posting.")
    keywords: JobKeywords = Field(
        description="Candidate skills and qualities requested by the job."
    )


class GenerationJob(BaseModel):
    title: str = Field(min_length=1)
    company: str = Field(min_length=1)
    description: str = Field(min_length=1)
    keywords: JobKeywords | None = Field(default_factory=JobKeywords)


class Technologies(ResumeSection):
    static: bool = False
    frontend: list[str] = Field(default_factory=list)
    backend: list[str] = Field(default_factory=list)
    database: list[str] = Field(default_factory=list)
    testing: list[str] = Field(default_factory=list)
    cicd: list[str] = Field(default_factory=list)
    cloud: list[str] = Field(default_factory=list)


class ContributionDraft(ContentModel):
    headline: str | None = None
    details: list[str] | None = None


class Contribution(ContentModel):
    headline: str
    details: list[str] = Field(default_factory=list)


class PositionDraft(ContentModel):
    index: int = 0
    company: str | None = None
    location: str | None = None
    title: str | None = None
    dates: str | None = None
    responsibilities: str | None = None
    contributions: list[ContributionDraft] | None = None


class Position(ResumeSection):
    static: bool = False
    index: int = 0
    company: str
    location: str | None = None
    title: str
    dates: str
    responsibilities: str
    contributions: list[Contribution] = Field(default_factory=list)


class Education(ResumeSection):
    static: bool = True
    qualification: str | None = None
    institution: str | None = None
    location: str | None = None
    date: str | None = None


type LanguageLevel = Literal["A1", "A2", "B1", "B2", "C1", "C2"]


class LanguageDetails(ContentModel):
    level: LanguageLevel | None = None
    note: str | None = None


class LanguageDraft(LanguageDetails):
    language: str | None = None


class Language(LanguageDetails):
    language: str


class AwardDraft(ContentModel):
    title: str | None = None
    description: str | None = None


class Award(ContentModel):
    title: str
    description: str


def _http_link(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or any(character.isspace() for character in value)
    ):
        raise ValueError("project link must be an HTTP(S) URL with a host")
    # Accessing port also rejects malformed port numbers.
    parsed.port
    return value


type ProjectLink = Annotated[
    str,
    Field(pattern=r"^https?://[^\s/?#]+(?:[/?#][^\s]*)?$"),
    AfterValidator(_http_link),
]


class ProjectDraft(ContributionDraft):
    link: str | None = None


class Project(Contribution):
    link: ProjectLink


class Contact(ResumeSection):
    static: bool = True
    phone: str | None = None
    email: str | None = None
    linkedin: str | None = None
    github: str | None = None


type Skills = list[list[str]]
type Checklist = list[str]


class ResumeDraft(ContentModel):
    technologies: Technologies | None = None
    skills: Skills | None = None
    responsibilities: str | None = None
    positions: list[PositionDraft] | None = None
    checklist: Checklist | None = None
    education: Education | None = None
    languages: list[LanguageDraft] | None = None
    awards: list[AwardDraft] | None = None
    projects: list[ProjectDraft] | None = None
    contact: Contact | None = None


class Resume(ContentModel):
    technologies: Technologies
    skills: Skills
    responsibilities: str = ""
    positions: list[Position]
    checklist: Checklist = Field(default_factory=list)
    education: Education = Field(default_factory=Education)
    languages: list[Language] = Field(default_factory=list)
    awards: list[Award]
    projects: list[Project]
    contact: Contact = Field(default_factory=Contact)


class ResumeRecord(ResumeDraft, RecordMetadata):
    job: str | None = None
    basis_for_resumes: JsonValue = None
    successful: int | bool | None = None


class GenerateRequest(BaseModel):
    job: GenerationJob | str
    resume: dict[str, Any] | str
    items: list[str] = Field(min_length=1, max_length=len(Resume.model_fields))

    @field_validator("items")
    @classmethod
    def validate_items(cls, items: list[str]) -> list[str]:
        if len(set(items)) != len(items):
            raise ValueError("items must not contain duplicates")
        unknown = set(items) - Resume.model_fields.keys()
        if unknown:
            raise ValueError(f"unknown resume item(s): {', '.join(sorted(unknown))}")
        return items


class GenerateResponse(BaseModel):
    resume: dict[str, Any]


class Application(ContentModel):
    """Decoded projection of the existing applications view, not a new entity."""

    successful: int | bool | None
    job_id: str | None
    resume_id: str | None
    job_item: JobRecord
    resume_item: ResumeRecord


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number is not supported: {value}")


def _validate_object_json(value: str) -> str:
    parsed = json.loads(value, parse_constant=_reject_json_constant)
    if not isinstance(parsed, dict):
        raise ValueError("stored JSON must be an object")
    return value


def _validate_json_text(value: str | None) -> str | None:
    if value is not None:
        json.loads(value, parse_constant=_reject_json_constant)
    return value


JOB_JSON_FIELDS = frozenset({"keywords"})
RESUME_JSON_FIELDS = frozenset({
    "technologies", "skills", "positions", "checklist", "education",
    "languages", "awards", "projects", "contact", "basis_for_resumes",
})


class StorageRow(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class JobRow(StorageRow):
    """Exact jobs table columns, before any JSON decoding."""

    id: str | None
    entry_date: str | None
    modified_date: str | None
    company: str | None
    favicon: str | None
    title: str | None
    link: str | None
    description: str | None
    keywords: str | None
    resume: str | None
    _json_text = field_validator("keywords")(_validate_json_text)


class ResumeRow(StorageRow):
    """Exact resumes table columns, including their nullable TEXT values."""

    id: str | None
    entry_date: str | None
    modified_date: str | None
    technologies: str | None
    skills: str | None
    responsibilities: str | None
    positions: str | None
    checklist: str | None
    education: str | None
    languages: str | None
    awards: str | None
    projects: str | None
    contact: str | None
    job: str | None
    basis_for_resumes: str | None
    successful: int | None
    _json_text = field_validator(*RESUME_JSON_FIELDS)(_validate_json_text)


class ApplicationRow(StorageRow):
    successful: int | None
    job_id: str | None
    resume_id: str | None
    job_item: str
    resume_item: str

    _object_json = field_validator("job_item", "resume_item")(_validate_object_json)
