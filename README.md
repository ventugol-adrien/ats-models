# ats-models

## Implemented core

The package provides shared Pydantic models, pure representation adapters,
resume section schemas/validators, and a `validate`/`schema` CLI. It does not
connect to databases, call providers, render documents, or alter SQL schemas.
`ingest-job` and `generate-resume` now import their Pydantic data models from this
package; other consumers are unchanged.

Its existing request/result models are available directly as
`JobDescriptionInput`, `JobDescription`, and `JobKeywords`. Their field
definitions live in the package's `models.py`; ingest only subclasses the result
model to add enrichment methods. Its existing JSON names are unchanged.

Generation's existing contracts are exported as `GenerationJob`,
`GenerateRequest`, and `GenerateResponse`, using the same shared `JobKeywords`.
Generation logic and item schemas stay in `generate-resume`.

Requires Python 3.14+ and Pydantic 2.14.3+. From this directory:

```sh
uv sync
uv run ats-models --help
```

### Python API

```python
from ats_models import (
    Job,
    Resume,
    Technologies,
    section_schema,
    validate_section,
)

job = Job(
    company="Example",
    title="Developer",
    description="Build reliable services.",
    link="https://example.com/jobs/1",
)
resume = Resume(
    technologies=Technologies(backend=["Python"]),
    skills=[["API design"]],
    positions=[],
    awards=[],
    projects=[],
)
skills_schema = section_schema("skills")
skills = validate_section("skills", [["Python", "API design"]])
```

Use `JobInput` and `ResumeDraft` for incomplete content, `Job` and `Resume` for
structurally complete content, and `JobRecord`/`ResumeRecord` for decoded stored
payloads. Draft and complete models are separate types rather than mutable
subclasses that narrow nullable fields.

`JobRow`, `ResumeRow`, and `ApplicationRow` mirror the actual SQL columns:
every row column is required, nullable columns accept null, and JSON text
remains text. The current schema has no whole-record `item_json` column;
individual columns are authoritative. Record readers do not enforce UUIDs, nonblank values,
parsed timestamps, or invented metadata.

`Application` mirrors the existing view's five columns. Its `job_item` and
`resume_item` are decoded records; there is no new application table, identity,
or lifecycle.

### Explicit adapters and lossless exports

```python
from ats_models import (
    JobInput,
    adapt_job_fields,
    parse_resume_payload,
    record_to_payload,
)

job_input = JobInput.model_validate(
    adapt_job_fields({"description": "Example", "job_url": ""})
)
source = {
    "id": "resume-1",
    "skills": ["Python"],
    "awards": [["Example", "Details"]],
    "custom": {"kept": True},
}
record = parse_resume_payload(source)
assert record.skills == [["Python"]]
assert record_to_payload(record, original=source) == source
```

- `adapt_job_fields` maps `job_url`, `created_at`, and `updated_at` to `link`,
  `entry_date`, and `modified_date`. Conflicting aliases raise `ValueError`;
  `db_insert` is rejected here because it belongs to the ingest request.
- `parse_job_payload` and `parse_resume_payload` accept an object or its JSON
  string/bytes. Resume parsing normalizes legacy flat skills and award pairs
  in memory without modifying the input.
- `job_from_row`, `resume_from_row`, and `application_from_row` accept validated
  row models or dictionaries such as `dict(sqlite_row)`. They decode JSON
  section columns or computed view items. SQL `id`,
  `entry_date`, `modified_date`, and resume `successful` values are authoritative:
  there are no stored whole-record metadata copies. Outcomes read from tables
  are SQLite integers; explicit payload parsing can still accept booleans.
  Application records take IDs and outcomes from the view; timestamps are not
  projected by the view. Parsing never writes storage and follows `resumes.job`,
  not `jobs.resume`.
- `job_to_row(record, original=row)` and
  `resume_to_row(record, original=row)` return row models, not database writes.
  Supplying the original preserves unchanged section JSON text and legacy
  nested shapes. Top-level fields without SQL columns are rejected; nested
  extras inside JSON sections are retained. SQL null cannot distinguish an
  omitted field from an explicit null; pure payload adapters still preserve
  that distinction.
- `record_to_payload(record, original=payload)` likewise preserves unchanged
  source representations. Changed sections use the shared nested shape.
  Without an original, exports use the decoded shared shape.
- Use these exporters for persistence: they retain omission while also
  capturing in-place changes to nested default collections. Plain Pydantic
  `exclude_unset=True` cannot capture every such mutation.
- `successful_as_bool` is an explicit, opt-in conversion for 0/1; other stored
  integers raise an error rather than being assigned an invented outcome.

All models preserve extra JSON-compatible payload fields. Validation and adapter
errors propagate; unsupported shapes are not silently repaired.

### CLI

```sh
# Validate decoded records or content.
printf '%s\n' '{"id":"job-1","link":""}' |
  uv run ats-models validate job-record

# Explicitly adapt an existing utility payload.
printf '%s\n' '{"job_url":"","description":"Example"}' |
  uv run ats-models validate job-input --source utility

# Decode and check a full SQLite row.
uv run ats-models validate resume-record row.json --source row

# Explicit JSONL: one complete object per line.
uv run ats-models validate job-record records.jsonl --jsonl

# Generate schemas directly from the model/section definitions.
uv run ats-models schema job-row
uv run ats-models schema --section positions
```

Model names are `job-input`, `job`, `job-record`, `job-row`, `resume-draft`,
`resume`, `resume-record`, `resume-row`, `application`, and `application-row`.
Input defaults to stdin; provide a file path or `-` explicitly if desired.
`--source row` decodes rows only for `job-record`, `resume-record`, and
`application`. `--source utility` adapts fields only for the three job
input/content/record models. Normal payload mode never guesses a row format.

Stdout contains validated JSON or JSON Schema. Record validation produces the
decoded shared shape, not a lossless legacy export; use the Python exporters
when writing an existing record. Validation failures exit 2 with field paths
on stderr; I/O errors exit 1. JSONL output is buffered until every line validates
so a failed batch does not emit a partial-success result.

### Validation

```sh
uv run python -m unittest discover -s tests
uv run pyright src/ats_models
uv build
```

Tests use synthetic records and temporary/in-memory databases, never personal
records. The three SQL contract tests read the current job-app-db schema
without touching a stored database. They explicitly
skip when that sibling checkout is absent; all other tests are standalone.
`jsonschema` and `pyright` are development dependencies only.

## Database-first contract and adoption plan

The plan below is historical and describes the original legacy CLI schema.
The implemented storage contract above now follows job-app-db's second
migration: `item_json` is removed and individual JSON columns are validated.
Legacy CLI persistence is not compatible with that migrated schema.

**Goal:** define jobs, resumes, and applications once, using the existing
database schemas as the source of truth. Every project should be able to import
the same validated Python types and exchange the same JSON without another
round of data modeling.

**Constraint:** keep database schemas intact. Do not rename columns, add tables
or columns, replace views, or migrate stored records to a newly designed shape.

The core above is implemented. Ingest's existing `JobDescriptionInput`,
`JobDescription`, and keyword field definitions are now centralized here,
without redesigning its CLI/API shapes. Extraction remains in ingest.
Generation's request/response/job models are also centralized without changing
its behavior. Transformer, renderer, and storage integration remain.

### 1. Current contracts and gaps

| Consumer | Current contract | Implication |
| --- | --- | --- |
| [generate-resume](../../generate-resume/src/generate_resume/generate.py) | Local `Job` and `JobKeywords`; resume input/output are dictionaries; IDs load `item_json`. | Replace duplicate job types; introduce typed draft/output validation without losing existing custom fields. |
| [Generation schemas](../../generate-resume/src/generate_resume/resume_items.py) | Handwritten schemas repeat resume sections and constraints. Generated JSON is parsed but not validated against the returned section's type. | Derive schemas and validate outputs from the same shared field definitions. |
| [latex-resume](../../latex-resume/src/latex_resume/models.py) | Pydantic components own rendering; `Resume` also loads SQLite records and compiles PDFs. Includes candidate-specific defaults and narrow enums/URLs. | Extract reusable data definitions, leaving rendering, profile defaults, and database access in consumers. |
| [ingest-job](../../utils/ingest-job/src/ingest_job/models.py) | A second keyword model; `JobDescription` includes timestamps, enrichment, favicon creation, and LLM extraction. | Separate input, domain data, stored records, and enrichment services. |
| [Ashby transformer](../../utils/transformer/libexec/platforms/ashby/job_description.py) | Partial job objects with `job_url`; absent values become empty strings. Outputs one JSON document per input object. | Target a shared job input contract; keep source parsing outside the package and document stream framing. |
| [CLI storage](../../../Dev/utils/latex-resume-cli/lib/db.sh) | `link`, `entry_date`, `modified_date`, JSON-encoded columns plus `item_json`; job/resume cross-links. `applications` is a join view with `successful`. | Match the existing tables and view exactly; adapt utility payloads to them without redesigning persistence. |
| [extract-jsonld](../../utils/extract-jsonld/README.md) and [scraper](../../utils/scraper/README.md) | Raw HTML and arbitrary JSON-LD arrays, with their own extraction storage. | Preserve raw source contracts; normalize only when producing domain jobs. |
| [latex-compiler](../../latex-compiler/README.md) | LaTeX input, PDF output. | No shared-model dependency needed. |

Concrete incompatibilities to cover:

- `job_url` versus `link`, and `created_at`/`updated_at` versus
  `entry_date`/`modified_date`.
- Flat skills accepted by generator tests versus nested skill rows required by
  the renderer; legacy award pairs versus award objects.
- Partial positions accepted by generation versus complete renderer components.
- Generator schemas allow some omitted fields while rendering supplies personal
  defaults; language-count and technology-count constraints also differ.
- Generator preserves arbitrary resume fields; stricter shared validation must
  not silently discard them.
- Stored IDs are non-empty strings, while the renderer HTTP GET requires UUIDs.
- Jobs point to resumes, resumes point to jobs, and application success lives on
  the resume. The shared package must preserve this relationship model and the
  existing view's join semantics, not introduce independent submissions.
- Python services default to a home-directory database, while the Bash CLI
  defaults to its checkout. Shape standardization does not resolve this path
  mismatch; consumer configuration must explicitly select the same store.

### 2. Design principles

1. **Database-first contracts.** Existing SQL definitions are authoritative for
   stored names, types, nullability, keys, and relationships. Python models mirror
   them; JSON Schema and section schemas derive from those aligned models.
2. **Data only.** Depend on Pydantic and the standard library. No FastAPI,
   Gemini, PyLaTeX, SQLite connections, network calls, credentials, or environment
   discovery during model import or validation.
3. **Separate stages.** Input/draft types describe incomplete data; content types
   describe resume sections; record types match stored data. Operations such as
   generation, insertion, and rendering remain consumer-owned.
4. **Explicit adaptation.** Shared record serialization uses database names.
   Utility-specific input/output conversion happens through named adapters,
   not silent fallback.
5. **No invented candidate facts.** Shared defaults may create empty collections,
   never employment history, contact details, qualifications, or language ability.
6. **No silent data loss.** Preserve additional data already supported by
   `item_json`. Do not require a new extension envelope or strip unknown payload
   fields during validation, generation, or consumer conversion.

### 3. Proposed public contract

Keep distribution name `ats-models` and import name
`ats_models`. Initially retain Python `>=3.14` and Pydantic v2,
matching the current Python consumers. Test the actual supported dependency
range rather than widening it speculatively.

| Type | Responsibilities |
| --- | --- |
| `JobKeywords` | `technologies`, `tech_skills`, `soft_skills`, `qualities`: lists of strings, with independent empty defaults. |
| `JobInput` | Partial input for transformation/enrichment, using database-aligned `link` with explicit `job_url` input adaptation. Operation flags such as `db_insert` stay in ingest requests. |
| `Job` / `JobRecord` | Shared job content and stored record types using `company`, `favicon`, `title`, `link`, `description`, `keywords`, `resume`; record identity and dates use `id`, `entry_date`, `modified_date`. |
| Resume components | `Technologies`, `Contribution`, `Position`, `Education`, `Language`, `Award`, `Project`, and `Contact`; no rendering methods. |
| `ResumeDraft` | Omissible sections and draft components for blank resumes, partial candidate bases, and generation. Preserve omitted versus explicitly supplied values. |
| `Resume` | Validated structural content for generation/rendering. Record parsing must still accommodate the SQL columns' nullability; rendering readiness/layout limits are checked separately. |
| `ResumeRecord` | Decoded resume sections plus existing `id`, `entry_date`, `modified_date`, `job`, `basis_for_resumes`, and `successful`. Do not rename or reinterpret provenance without evidence. |
| `JobRow`, `ResumeRow`, `ApplicationRow` | Exact SQL table/view columns, with JSON stored as text. `item_json` is a row field; decoded record models represent its payload separately. |
| `Application` | Read model matching the existing view: `successful`, `job_id`, `resume_id`, `job_item`, `resume_item`. No new stored application ID, status, outcome, or submission timestamp. |
| `ResumeSection` | The current ten selectable content sections, derived from the shared section registry. |

For v1, retain familiar resume structure: technologies by the existing six
categories, `skills: list[list[str]]`, responsibilities text, positions,
checklist, singular education, languages, award objects, project objects, and
contact. Header/profile configuration stays in the renderer rather than adding
stored fields. Multiple education entries and redesigned skill taxonomies are
outside this package's initial scope.

Generalize candidate-specific constraints: languages are not limited to five
names, CEFR levels support A1-C2 when supplied, proficiency notes are free text,
and project links allow valid HTTP(S) URLs rather than a personal allowlist.
Technology minimums, checklist length, language counts, and layout ordering
belong in consumer policies, not universal domain validity.

The SQL schemas fix the outer storage shape, but do not fully specify the nested
JSON in text columns. Establish those nested types from the existing
serialization code, renderer, and tests. Where they disagree, document one
shared interpretation and an explicit adapter; do not change SQL to resolve it.

Use standard JSON serialization with these rules:

- Shared stored names are `link`, `entry_date`, `modified_date`, `resume`, `job`,
  and `basis_for_resumes`. `job_id`/`resume_id` belong to the application view.
- Mirror SQL nullability and storage types. Do not add UUID-only, nonblank,
  required timestamp, or timezone rules to record readers that reject data the
  database permits. Stricter operation requirements stay in consumer validation.
- Preserve timestamp strings as stored. Do not convert naive values to an
  assumed timezone, generate missing dates, or change their serialized form.
- Preserve free-form position `dates` and education `date`; these are display
  periods, not reliable machine timestamps.
- Version package releases and exported schema artifacts without introducing
  `schema_version` into stored payloads.
- Preserve existing additional `item_json` fields in place. Known extra fields
  such as ingest's location/domain can be typed when supported by evidence, but
  must not become new SQL columns or mandatory fields.
- Omitted patch fields mean unchanged. Explicit null clears only nullable fields.
  Use `model_fields_set`/`exclude_unset`; never implement updates by dumping all
  defaults over an existing record.

The application model reflects the existing view:
`jobs JOIN resumes ON jobs.id = resumes.job`, with `resumes.successful`.
Do not substitute the opposite `jobs.resume` link or assume both links always
agree. Preserve `successful` values and nulls; normalize SQLite 0/1 to a JSON
boolean only under an explicit, tested conversion. Do not infer rejection,
submission state, or additional application identities.

### 4. Package layout and reuse API

Start small:

```text
src/ats_models/
    __init__.py       # intentional public exports, no placeholder greeting
    models.py         # shared content, draft, record, and application types
    schemas.py        # section registry and schema generation
    compatibility.py  # pure row/payload and utility-boundary conversions
    cli.py            # validate/schema commands for non-Python consumers
tests/
    test_models.py
    test_schemas.py
    test_compatibility.py
    test_cli.py
```

Do not split models into a larger hierarchy until size warrants it. Consumers
should normally import `Job`, `JobKeywords`, `Resume`, and `Application` directly
from the package. Do not add a generic CRUD layer, shared server, plugin system,
or abstract repository framework.

Provide a section-schema helper and corresponding section validator backed by
the same Pydantic field definitions/`TypeAdapter`s. Keep required output
constraints explicit: a generated section must satisfy its declared type, even
when the resume basis is only a draft. Preserve `$defs` and reference resolution;
adapt provider-specific schema restrictions in the generator, not the core.

Provide `validate` and `schema` CLI subcommands for jobs, resumes, records, and
applications. Accept a documented single-object or explicit JSONL mode; do not
heuristically accept concatenated pretty-printed documents. Validation failures
exit nonzero with field paths on stderr; stdout remains machine-readable.
Any generated schema exports must be reproducible and checked against models,
not maintained as a second source of truth.

### 5. Compatibility without database changes

Pure adapters should:

1. Map utility `job_url` to database `link`, and utility `created_at`/`updated_at`
   to `entry_date`/`modified_date` at explicit boundaries. Reject contradictory
   values when both naming schemes are supplied.
2. Distinguish a complete SQLite row, its `item_json` payload, and decoded
   content. Provide explicit entry points for each rather than guessing from
   string values. Preserve the existing `item_json` contract and report conflicts
   with projected columns rather than automatically repairing the database.
3. Decode JSON-encoded section columns. Support valid award pairs and flat skill
   lists through documented in-memory adapters; retain the source representation
   for unchanged legacy writes. Reject malformed/mixed values explicitly.
4. Preserve empty strings, nulls, missing keywords, and explicitly empty keywords
   where the storage contract distinguishes them. Any consumer normalization
   must be explicit and must not rewrite stored values as a side effect.
5. Preserve custom payload fields and both existing relationship directions.
   Round-trip fixtures must verify that unrelated fields are not changed.
6. Parse application-view rows, including JSON-encoded `job_item` and
   `resume_item`, without adding identifiers or changing join behavior.

Keep all schema initialization SQL and extraction storage SQL unchanged.
Consumer repositories continue reading/writing their existing tables and
columns. The shared package only validates and converts representations in
memory. Inspect deployed schemas read-only before wiring consumers, because
checkout SQL and existing databases may differ; report discrepancies rather
than issuing DDL or a data migration.

### 6. Implementation sequence and completion gates

| Phase | Work | Completion gate |
| --- | --- | --- |
| 1. Freeze the contract | Build the field/type/nullability/key matrix from existing SQL; document nested JSON from consumers and tests. Create synthetic row, payload, draft, and view fixtures. | Every shared stored field traces to existing SQL; nested conventions and consumer-only constraints are explicit. |
| 2. Build the package (implemented) | Models, public exports, compatibility helpers, schema helpers, CLI, README quickstarts, tests, and build metadata are now present. | Clean install and import work without credentials, databases, or rendering/provider dependencies; round trips and CLI validation pass. |
| 3. Migrate ingest and transform | Use shared keywords/job types; move extraction/favicon behavior to ingest services; keep `db_insert` in ingest request types only. Adapt utility names to database names and preserve old external interfaces during transition. Document transformer framing. | CLI and HTTP share validation; insertion uses existing database/API names; supplied fields, extraction concurrency, and failures remain tested. |
| 4. Migrate generation | Replace local models/manual schemas; type draft basis and outputs; validate each generated section and merged content. Resolve IDs in a local repository adapter. | Valid output passes shared validation; invalid output fails explicitly, retains the section name, and returns no partial success. IDs, custom payload fields, and untouched sections survive. |
| 5. Migrate rendering | Import shared data; move rendering to functions/adapters. Preserve old `from_json`/`from_id`/render conveniences as temporary delegating wrappers if callers need them. Keep candidate defaults in an explicit local profile and layout restrictions local. | Equivalent explicit profile/data produces equivalent LaTeX and valid PDF; existing HTTP content negotiation, ID lookup, and errors remain unchanged. |
| 6. Integrate storage/applications | Add shared row/payload adapters and the application-view read model; wire compatible Bash validation into ingest/modify/put/patch/paste boundaries. Keep DDL, stored names, relationships, and view unchanged. | Existing CRUD/query behavior passes; source payloads retain their fields; applications match the existing SQL view; no schema or bulk data migration occurs. |
| 7. Release and simplify onboarding | Add shared dependency to each Python consumer, refresh locks, publish/install an immutable release, and remove duplicate definitions after compatibility gates pass. | A clean new consumer can import models, validate JSON, and obtain schemas using documented examples without copying definitions. |

Phases 3-5 depend on the package, not on each other. Coordinate their shared-store
configuration before phase 6 integration. Raw extraction and PDF compilation
do not require migration.

For local development, use `uv` path/editable sources in consumer manifests;
release manifests must depend on published versions, not machine-specific
absolute paths. Verify distribution names separately from import names:
the renderer currently declares distribution `job-application-server`.

### 7. Validation and rollout

- Package tests: SQL-aligned requiredness/nullability, independent defaults,
  nested types, preservation of stored IDs/dates/empty values, extra payload
  round trips, database names, and boundary conflict reporting.
- Schema tests: each selectable section has one schema/validator; references
  resolve; valid/invalid fixtures agree between schema and Python validation.
- Consumer tests: replace permissive fake generator results with schema-valid
  results, then add explicit invalid-output cases. Preserve concurrency, custom
  fields, read-only lookup, and existing HTTP/CLI error contracts.
- Rendering tests: use synthetic, complete profile data for deterministic
  package/consumer checks. Existing renderer tests rely on a local personal
  database; keep that coverage as explicitly configured integration coverage,
  not a prerequisite for shared-package tests.
- Storage tests: temporary SQLite databases created from unchanged SQL; compare
  columns, keys, and view definitions to the source schema. Verify row/payload
  conversions, projection conflicts, unchanged CRUD behavior, and exact
  application-view results, including differing relationship directions.
- End-to-end contract test: synthetic JSON-LD -> transformer -> mocked ingest
  enrichment -> stored job -> mocked resume generation -> shared validation ->
  renderer -> existing application view -> shared application model. No external
  model call or private fixture is
  required; compiler/PDF integration runs separately when its tools are available.

Use the existing `unittest` runners for Python consumers and targeted shell CLI
tests. Run package tests first, then affected consumer selectors, then the
synthetic pipeline. Exercise built artifacts in a clean environment.

Breaking Python/utility interfaces require documented release notes and
compatibility adapters, including during pre-1.0 development. Database names
and semantics stay fixed for this work. Remove duplicate consumer definitions
only after all known consumers pass the compatibility suite.

**Success criteria:** no duplicate job/keyword/content definitions in migrated
consumers; no independently handwritten resume schemas; one database-aligned
record contract; unchanged database schemas and stored data; all existing
representations either parse without loss or report a specific incompatibility;
existing UX is preserved or explicitly versioned; and new projects can use the
package directly through tested examples.

### Decisions before implementation

- Verify the deployed schemas match the inspected SQL definitions and identify
  any existing schema variants without modifying them.
- Confirm the encoding/semantics of `basis_for_resumes` and `successful` before
  adding stricter nested types or boolean conversions.
- Confirm which remote API owns jobs/resumes, its accepted payloads, and the
  executable/alias behind ingest's `jds` command.
- Choose package distribution/CI location and the supported transition window.
- Approve general-purpose domain validation while retaining current personal
  defaults and formatting constraints in the renderer's explicit profile.

The remote API implementation and `jds` executable were not established by the
inspected files. Their contracts must be verified before migrating writes.