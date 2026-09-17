"""JSON Schema (draft 2020-12) validation for island.yaml (2.1-a)."""
from __future__ import annotations

import json
from importlib import resources
from typing import Any

from jsonschema import Draft202012Validator

from .issues import Issue
from .yaml_io import line_of, path_str

SCHEMA_VERSION = "v0"


def load_schema() -> dict[str, Any]:
    text = (
        resources.files("island_init")
        .joinpath("schemas", f"island.schema.{SCHEMA_VERSION}.json")
        .read_text(encoding="utf-8")
    )
    return json.loads(text)


def validate_schema(data: Any, root: Any | None = None) -> list[Issue]:
    """Validate `data` against the island.yaml schema.

    `root` is the same document with line info attached (see yaml_io.load);
    pass it separately because jsonschema errors reference sub-paths of
    `data`, and `data` and `root` are usually the same object.
    """
    if root is None:
        root = data
    validator = Draft202012Validator(load_schema())
    issues: list[Issue] = []
    for error in sorted(validator.iter_errors(data), key=lambda e: list(e.path)):
        path = tuple(error.path)
        field = path_str(path) or "<root>"
        issues.append(Issue(field=field, message=error.message, line=line_of(root, path)))
    return issues
