"""What a parser must do."""

from typing import Protocol


class ParseFailure(Exception):
    """No usable request. The pipeline reports this and shows no number."""


class Parser(Protocol):
    name: str

    def parse(self, question: str, store, session) -> "QueryRequest":  # noqa: F821
        ...
