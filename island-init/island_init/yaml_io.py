"""YAML loading that keeps line numbers, so errors can name a line (2.1-a).

ruamel.yaml's round-trip loader attaches source line/column info to every
CommentedMap/CommentedSeq it builds (the `.lc` accessor) without changing
how the data reads as plain dicts/lists -- both jsonschema and our own
semantic checks can use the result directly.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

_yaml = YAML(typ="rt")

_dump_yaml = YAML(typ="safe")
_dump_yaml.default_flow_style = False
_dump_yaml.sort_base_mapping_type_on_output = False  # preserve insertion order
_dump_yaml.indent(mapping=2, sequence=4, offset=2)


def load(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return _yaml.load(f)


def dump(data: Any, path: Path) -> None:
    """Writes a plain dict/list structure as YAML (2.1-c: island-init new's
    freshly-built island.yaml has no prior comments/formatting to preserve,
    so this is a plain dump, not a round-trip one)."""
    with path.open("w", encoding="utf-8") as f:
        _dump_yaml.dump(data, f)


def line_of(root: Any, path: tuple[Any, ...]) -> int | None:
    """1-indexed source line of the value at `path` (a tuple of keys/indices).

    Best-effort: returns None if the container has no line info (e.g. it
    isn't a CommentedMap/CommentedSeq -- a plain dict built for a test
    fixture) or the path doesn't resolve.
    """
    node = root
    for i, key in enumerate(path):
        last = i == len(path) - 1
        if last:
            try:
                if isinstance(node, CommentedMap):
                    line, _col = node.lc.value(key)
                    return line + 1
                if isinstance(node, CommentedSeq):
                    line, _col = node.lc.item(key)
                    return line + 1
            except Exception:
                return None
            return None
        try:
            node = node[key]
        except (KeyError, IndexError, TypeError):
            return None
    if isinstance(node, (CommentedMap, CommentedSeq)) and node.lc.line is not None:
        return node.lc.line + 1
    return None


def path_str(path: tuple[Any, ...]) -> str:
    out = ""
    for key in path:
        if isinstance(key, int):
            out += f"[{key}]"
        else:
            out += f".{key}" if out else str(key)
    return out
