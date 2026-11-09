import json
from collections.abc import Mapping
from typing import Literal

from pydantic import JsonValue, TypeAdapter

from .models import (
    Application,
    ApplicationRow,
    JobRecord,
    JobRow,
    JOB_JSON_FIELDS,
    ResumeRecord,
    ResumeRow,
    RESUME_JSON_FIELDS,
    _reject_json_constant,
)

type Payload = dict[str, JsonValue]
type PayloadInput = Mapping[str, JsonValue] | str | bytes | bytearray

_payload_adapter = TypeAdapter(Payload)


def _same_json(left: object, right: object) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(
            _same_json(value, right[name]) for name, value in left.items()
        )
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            _same_json(a, b) for a, b in zip(left, right, strict=True)
        )
    return left == right


def _merge_fields(explicit: JsonValue, nondefault: JsonValue) -> JsonValue:
    if isinstance(explicit, dict) and isinstance(nondefault, dict):
        result = dict(explicit)
        for name, value in nondefault.items():
            result[name] = (
                _merge_fields(result[name], value) if name in result else value
            )
        return result
    if (
        isinstance(explicit, list)
        and isinstance(nondefault, list)
        and len(explicit) == len(nondefault)
    ):
        return [
            _merge_fields(a, b) for a, b in zip(explicit, nondefault, strict=True)
        ]
    return nondefault


def _record_payload(record: JobRecord | ResumeRecord) -> Payload:
    # exclude_unset alone loses in-place edits to omitted default collections.
    explicit = _payload_adapter.validate_python(
        record.model_dump(mode="json", exclude_unset=True)
    )
    nondefault = _payload_adapter.validate_python(
        record.model_dump(mode="json", exclude_defaults=True)
    )
    return _payload_adapter.validate_python(_merge_fields(explicit, nondefault))


def parse_json_object(data: str | bytes | bytearray) -> Payload:
    parsed = json.loads(data, parse_constant=_reject_json_constant)
    if not isinstance(parsed, dict):
        raise ValueError("JSON input must be an object")
    return _payload_adapter.validate_python(parsed, strict=True)


def _payload(data: PayloadInput) -> Payload:
    if isinstance(data, (str, bytes, bytearray)):
        return parse_json_object(data)
    return _payload_adapter.validate_python(dict(data), strict=True)


def adapt_job_fields(data: PayloadInput) -> Payload:
    """Translate utility field names explicitly, without modifying the input."""
    result = _payload(data)
    for utility, stored in (
        ("job_url", "link"),
        ("created_at", "entry_date"),
        ("updated_at", "modified_date"),
    ):
        if utility in result:
            if stored in result and result[stored] != result[utility]:
                raise ValueError(f"conflicting job fields: {utility} and {stored}")
            result[stored] = result.pop(utility)
    if "db_insert" in result:
        raise ValueError("db_insert is an ingest request flag, not job data")
    return result


def parse_job_payload(data: PayloadInput) -> JobRecord:
    return JobRecord.model_validate(_payload(data))


def _normalize_resume(data: Payload) -> Payload:
    result = dict(data)
    skills = result.get("skills")
    if isinstance(skills, list) and skills:
        if all(isinstance(skill, str) for skill in skills):
            result["skills"] = [skills]
        elif any(isinstance(skill, str) for skill in skills):
            raise ValueError("skills must be all strings or all string rows")
    awards = result.get("awards")
    if isinstance(awards, list):
        converted: list[JsonValue] = []
        for index, award in enumerate(awards):
            if isinstance(award, list):
                if len(award) != 2 or not all(
                    isinstance(value, str) for value in award
                ):
                    raise ValueError(
                        f"awards.{index}: legacy award must contain two strings"
                    )
                converted.append({"title": award[0], "description": award[1]})
            else:
                converted.append(award)
        result["awards"] = converted
    return result


def parse_resume_payload(data: PayloadInput) -> ResumeRecord:
    """Decode legacy nested shapes in memory; use export to preserve originals."""
    return ResumeRecord.model_validate(_normalize_resume(_payload(data)))


def _with_metadata(payload: Payload, metadata: Mapping[str, JsonValue]) -> Payload:
    result = dict(payload)
    for name, value in metadata.items():
        if name not in result and value is None:
            continue
        if (
            name == "successful"
            and isinstance(result.get(name), bool)
            and result[name] == value
        ):
            continue
        result[name] = value
    return result


def _row_payload(row: JobRow | ResumeRow) -> Payload:
    json_fields = JOB_JSON_FIELDS if isinstance(row, JobRow) else RESUME_JSON_FIELDS
    payload = {}
    for name, value in row.model_dump().items():
        if value is None:
            continue
        if name in json_fields:
            try:
                payload[name] = json.loads(value, parse_constant=_reject_json_constant)
            except ValueError as error:
                raise ValueError(f"{name}: invalid JSON in SQL column") from error
        else:
            payload[name] = value
    return _payload_adapter.validate_python(payload, strict=True)


def job_from_row(data: JobRow | Mapping[str, object]) -> JobRecord:
    row = data if isinstance(data, JobRow) else JobRow.model_validate(dict(data))
    return parse_job_payload(_row_payload(row))


def resume_from_row(data: ResumeRow | Mapping[str, object]) -> ResumeRecord:
    row = data if isinstance(data, ResumeRow) else ResumeRow.model_validate(dict(data))
    return parse_resume_payload(_row_payload(row))


def application_from_row(
    data: ApplicationRow | Mapping[str, object],
) -> Application:
    row = (
        data
        if isinstance(data, ApplicationRow)
        else ApplicationRow.model_validate(dict(data))
    )
    job = parse_job_payload(
        _with_metadata(parse_json_object(row.job_item), {"id": row.job_id})
    )
    resume = parse_resume_payload(
        _with_metadata(
            parse_json_object(row.resume_item),
            {"id": row.resume_id, "successful": row.successful},
        )
    )
    if "job" in resume.model_fields_set and resume.job != row.job_id:
        raise ValueError("job: resume_item conflicts with the view join")
    return Application(
        successful=row.successful,
        job_id=row.job_id,
        resume_id=row.resume_id,
        job_item=job,
        resume_item=resume,
    )


def record_to_payload(
    record: JobRecord | ResumeRecord,
    *,
    original: PayloadInput | None = None,
) -> Payload:
    """Retain unchanged legacy encodings; omitted fields are never default-filled."""
    current = _record_payload(record)
    if original is None:
        return current
    source = _payload(original)
    parsed = (
        parse_resume_payload(source)
        if isinstance(record, ResumeRecord)
        else parse_job_payload(source)
    )
    normalized = _record_payload(parsed)
    for name in current:
        if name in source and _same_json(current[name], normalized.get(name)):
            current[name] = source[name]
    return current


def _row_values(
    payload: Payload,
    kind: Literal["job", "resume"],
    original: JobRow | ResumeRow | None,
) -> dict[str, object]:
    row_type = JobRow if kind == "job" else ResumeRow
    unknown = payload.keys() - row_type.model_fields.keys()
    if unknown:
        raise ValueError(f"Fields without {kind} SQL columns: {sorted(unknown)!r}")
    json_fields = JOB_JSON_FIELDS if kind == "job" else RESUME_JSON_FIELDS
    original_record_payload = (
        _row_payload(original) if original is not None else None
    )
    values: dict[str, object] = {}
    for name in row_type.model_fields:
        value = payload.get(name)
        if name in json_fields and value is not None:
            projected: object = json.dumps(value, ensure_ascii=False, allow_nan=False)
        elif isinstance(value, bool):
            projected = int(value) if name == "successful" else str(int(value))
        else:
            projected = value
        if (
            original is not None
            and original_record_payload is not None
            and _same_json(value, original_record_payload.get(name))
        ):
            projected = getattr(original, name)
        values[name] = projected
    return values


def job_to_row(
    record: JobRecord, *, original: JobRow | None = None
) -> JobRow:
    source = _row_payload(original) if original is not None else None
    payload = record_to_payload(record, original=source)
    return JobRow.model_validate(_row_values(payload, "job", original))


def resume_to_row(
    record: ResumeRecord, *, original: ResumeRow | None = None
) -> ResumeRow:
    source = _row_payload(original) if original is not None else None
    payload = record_to_payload(record, original=source)
    return ResumeRow.model_validate(_row_values(payload, "resume", original))


def successful_as_bool(value: int | bool | None) -> bool | None:
    """Opt-in 0/1 conversion; other SQLite integers are not outcomes."""
    if value is None or isinstance(value, bool):
        return value
    if not isinstance(value, int) or value not in (0, 1):
        raise ValueError("successful must be 0, 1, a boolean, or null")
    return bool(value)
