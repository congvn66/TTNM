"""Core package for the report QA backend.

The package is intentionally dependency-light while the runtime stack is being
scaffolded. Domain objects and application flows can be exercised without a
database, HTTP server, or model provider.
"""

__all__ = ["domain", "application", "infrastructure", "worker"]

