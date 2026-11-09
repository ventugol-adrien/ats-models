import argparse
import json
import sys
from pathlib import Path

from pydantic import BaseModel

from .compatibility import (
    adapt_job_fields,
    application_from_row,
    job_from_row,
    parse_json_object,
    parse_resume_payload,
    resume_from_row,
)
from .models import (
    Application,
    ApplicationRow,
    Job,
    JobInput,
    JobRecord,
    JobRow,
    Resume,
    ResumeDraft,
    ResumeRecord,
    ResumeRow,
)
from .schemas import ResumeSection, section_schema

MODELS: dict[str, type[BaseModel]] = {
    "job-input": JobInput,
    "job": Job,
    "job-record": JobRecord,
    "job-row": JobRow,
    "resume-draft": ResumeDraft,
    "resume": Resume,
    "resume-record": ResumeRecord,
    "resume-row": ResumeRow,
    "application": Application,
    "application-row": ApplicationRow,
}


def _validate(kind: str, source: str, data: str) -> BaseModel:
    payload = parse_json_object(data)
    if source == "row":
        if kind == "job-record":
            return job_from_row(payload)
        if kind == "resume-record":
            return resume_from_row(payload)
        if kind == "application":
            return application_from_row(payload)
        raise ValueError("--source row requires job-record, resume-record, or application")
    if source == "utility":
        if kind not in ("job-input", "job", "job-record"):
            raise ValueError("--source utility requires job-input, job, or job-record")
        payload = adapt_job_fields(payload)
    if kind == "resume-record":
        return parse_resume_payload(payload)
    return MODELS[kind].model_validate(payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ats-models")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate", help="validate and print JSON")
    validate.add_argument("kind", choices=MODELS)
    validate.add_argument("input", nargs="?", default="-", help="JSON file or - for stdin")
    validate.add_argument("--jsonl", action="store_true", help="one JSON object per line")
    validate.add_argument("--source", choices=("payload", "row", "utility"), default="payload")
    schema = subparsers.add_parser("schema", help="print model or resume section JSON Schema")
    schema.add_argument("kind", nargs="?", choices=MODELS)
    schema.add_argument("--section", choices=list(ResumeSection))
    args = parser.parse_args(argv)
    try:
        if args.command == "schema":
            if (args.kind is None) == (args.section is None):
                parser.error("schema requires either KIND or --section SECTION")
            value = (
                section_schema(args.section)
                if args.section is not None
                else MODELS[args.kind].model_json_schema()
            )
            output = json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)
        else:
            if args.input == "-":
                if sys.stdin.isatty():
                    raise ValueError("provide a JSON file or pipe JSON on stdin")
                data = sys.stdin.read()
            else:
                data = Path(args.input).read_text(encoding="utf-8")
            if not data.strip():
                raise ValueError("input is empty")
            documents = data.splitlines() if args.jsonl else [data]
            results: list[str] = []
            for index, document in enumerate(documents, start=1):
                try:
                    model = _validate(args.kind, args.source, document)
                except ValueError as error:
                    if args.jsonl:
                        raise ValueError(f"line {index}: {error}") from error
                    raise
                results.append(
                    json.dumps(
                        model.model_dump(mode="json", exclude_unset=True),
                        ensure_ascii=False,
                        indent=None if args.jsonl else 2,
                        allow_nan=False,
                    )
                )
            output = "\n".join(results)
        sys.stdout.write(output + "\n")
    except ValueError as error:
        print(f"ats-models: {error}", file=sys.stderr)
        return 2
    except OSError as error:
        print(f"ats-models: {error}", file=sys.stderr)
        return 1
    return 0
