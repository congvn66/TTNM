"""Stable domain errors mapped to transport errors by a future API layer."""


class DomainError(Exception):
    """Base class for expected business failures."""

    code = "domain_error"


class InvariantError(DomainError):
    code = "invariant_violation"


class ConflictError(DomainError):
    code = "revision_conflict"


class NotFoundError(DomainError):
    code = "not_found"

