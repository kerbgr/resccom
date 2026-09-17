"""Shared result type for schema and semantic validation (2.1-a)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Issue:
    """One validation failure, always naming the field path and (if known) line."""

    field: str
    message: str
    line: int | None = None  # 1-indexed

    def render(self, path: str) -> str:
        where = f"{path}:{self.line}" if self.line is not None else path
        return f"{where}: {self.field}: {self.message}"
