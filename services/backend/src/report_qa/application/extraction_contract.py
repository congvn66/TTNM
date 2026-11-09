"""Full schema validation at the extraction boundary (including nested fields)."""

import json
from functools import lru_cache
from importlib.resources import files

from jsonschema import Draft202012Validator, FormatChecker

from report_qa.domain.contracts import validate_document_evidence_v2


@lru_cache(maxsize=1)
def _validator():
    schema = files("report_qa.resources").joinpath("document-evidence-v2.schema.json")
    return Draft202012Validator(
        json.loads(schema.read_text()), format_checker=FormatChecker()
    )


def validate_extraction_batch(batch):
    _validator().validate(batch)
    return validate_document_evidence_v2(batch)
