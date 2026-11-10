"""Enums and validation helpers shared by domain/application code."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Iterable, Sequence

from .errors import InvariantError


class ValueKind(StrEnum):
    NUMBER = "number"
    TEXT = "text"


class DataStatus(StrEnum):
    VALID = "valid"
    MISSING = "missing"
    ERROR = "error"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class MessageStatus(StrEnum):
    ACCEPTED = "accepted"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    NEEDS_UPDATE = "needs_update"


class AnswerStatus(StrEnum):
    ANSWERED = "answered"
    NEEDS_CLARIFICATION = "needs_clarification"
    INSUFFICIENT_DATA = "insufficient_data"
    SOURCE_CONFLICT = "source_conflict"
    PROCESSING_ERROR = "processing_error"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"


class EvidenceAction(StrEnum):
    VERIFY = "verify"
    EDIT = "edit"
    MARK_ERROR = "mark_error"
    RESTORE = "restore"


DECIMAL_RE = re.compile(r"^-?(0|[1-9][0-9]*)(\.[0-9]+)?$")


def validate_decimal_text(value: str | None) -> str | None:
    """Validate the wire representation used for exact decimal values."""

    if value is None:
        return None
    if not isinstance(value, str) or not DECIMAL_RE.fullmatch(value):
        raise InvariantError("decimal must be an exact non-exponent string")
    return value


def validate_bbox(bbox: Sequence[float] | None) -> tuple[float, float, float, float] | None:
    """Validate normalized top-left coordinates in the inclusive unit square."""

    if bbox is None:
        return None
    if len(bbox) != 4:
        raise InvariantError("bbox must contain four coordinates")
    x0, y0, x1, y1 = tuple(float(item) for item in bbox)
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        raise InvariantError("bbox must satisfy 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1")
    return x0, y0, x1, y1


def require_unique(values: Iterable[str], label: str) -> tuple[str, ...]:
    result = tuple(values)
    if len(result) != len(set(result)):
        raise InvariantError(f"{label} must contain unique values")
    return result
