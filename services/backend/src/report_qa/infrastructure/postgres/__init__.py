"""PostgreSQL infrastructure boundary.

The first cutover milestone owns configuration, connectivity and migrations.
Domain/application code must depend on ports, not import this package.
"""

from .health import postgres_health
from .revision_store import PostgresRevisionStore

__all__ = ["postgres_health", "PostgresRevisionStore"]
