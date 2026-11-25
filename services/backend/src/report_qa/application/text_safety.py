"""Remove characters that storage cannot hold.

PostgreSQL rejects U+0000 in text and jsonb, and UTF-8 cannot encode lone
surrogates. Both can arrive from PDF text, model output or a client request,
and one such character makes every later save of that session fail.
"""

from __future__ import annotations

import re
from typing import Any

_UNSTORABLE = re.compile("[\x00\ud800-\udfff]")


def storable(value: Any) -> Any:
    """The same value with unstorable characters removed from every string."""
    if isinstance(value, str):
        return _UNSTORABLE.sub("", value)
    if isinstance(value, dict):
        return {storable(key): storable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [storable(item) for item in value]
    return value
