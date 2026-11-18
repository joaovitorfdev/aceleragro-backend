"""Evaluator for the proposal form schema rules (see docs/form-contract.md).

The schema (``form_schema/proposal_form.json``) is the only place where visibility
(``visible_when``) and requiredness (``required``) are defined. This module loads it
once and evaluates the rules against a *values* dict shaped like the form state::

    {"proponent": {...}, "properties": [{...}], "credit": {...}, "debts": [], "review": {}}
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

SCHEMA_PATH = Path(__file__).resolve().parent / "form_schema" / "proposal_form.json"

RULE_OPS = frozenset({"eq", "ne", "in", "not_in", "filled", "empty"})


@lru_cache(maxsize=1)
def load_schema() -> dict[str, Any]:
    """Parse the form schema once per process."""
    with SCHEMA_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def schema_bytes() -> bytes:
    """Raw schema bytes (served verbatim by ``GET /api/forms/proposal``)."""
    return SCHEMA_PATH.read_bytes()


def get_section(section_id: str) -> dict[str, Any] | None:
    for section in load_schema()["sections"]:
        if section["id"] == section_id:
            return section
    return None


def get_field(section_id: str, field_id: str) -> dict[str, Any] | None:
    section = get_section(section_id)
    if section is None:
        return None
    for field in section["fields"]:
        if field["id"] == field_id:
            return field
    return None


def default_min_confidence() -> str:
    return load_schema()["autofill"]["default_min_confidence"]


@dataclass(frozen=True)
class RuleContext:
    """Where a rule is evaluated: the whole values dict plus the section/item scope."""

    values: dict[str, Any]
    section: str
    index: int | None = None

    @property
    def base(self) -> str:
        """Prefix used to resolve ``@.<field>`` paths."""
        if self.index is None:
            return self.section
        return f"{self.section}.{self.index}"


def is_empty(value: Any) -> bool:
    """None, blank strings and empty containers are empty; ``False`` and ``0`` are not."""
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, list | dict | tuple | set):
        return len(value) == 0
    return False


def resolve_path(values: dict[str, Any], path: str) -> Any:
    """Resolve an absolute path (``section.field`` / ``section.<i>.field``); None if absent."""
    node: Any = values
    for part in path.split("."):
        if isinstance(node, dict):
            node = node.get(part)
        elif isinstance(node, list):
            try:
                node = node[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
        if node is None:
            return None
    return node


def _absolute(path: str, ctx: RuleContext) -> str:
    if path.startswith("@."):
        return f"{ctx.base}.{path[2:]}"
    return path


def evaluate_rule(rule: dict[str, Any] | None, ctx: RuleContext) -> bool:
    """Evaluate ``{field, op, value?}`` or ``{all: [...]}`` / ``{any: [...]}``."""
    if not rule:
        return True
    if "all" in rule:
        return all(evaluate_rule(r, ctx) for r in rule["all"])
    if "any" in rule:
        return any(evaluate_rule(r, ctx) for r in rule["any"])

    op = rule["op"]
    if op not in RULE_OPS:
        raise ValueError(f"Unknown rule op: {op}")
    actual = resolve_path(ctx.values, _absolute(rule["field"], ctx))
    expected = rule.get("value")

    if op == "filled":
        return not is_empty(actual)
    if op == "empty":
        return is_empty(actual)
    if op == "eq":
        return actual is not None and actual == expected
    if op == "ne":
        return actual != expected
    if op == "in":
        return actual is not None and actual in (expected or [])
    # not_in
    return actual not in (expected or [])


def is_visible(field: dict[str, Any], ctx: RuleContext) -> bool:
    """A field without ``visible_when`` is always visible."""
    return evaluate_rule(field.get("visible_when"), ctx)


def is_required(field: dict[str, Any], ctx: RuleContext) -> bool:
    """Required means: flagged ``required`` in the schema **and** currently visible."""
    return bool(field.get("required")) and is_visible(field, ctx)


def is_missing(field: dict[str, Any], value: Any) -> bool:
    """Whether a required field's value counts as not provided.

    Booleans (declarations) are only satisfied by ``True``.
    """
    if field["type"] == "boolean":
        return value is not True
    return is_empty(value)


def iter_field_contexts(
    values: dict[str, Any],
) -> Iterator[tuple[str, dict[str, Any], dict[str, Any], RuleContext]]:
    """Yield ``(path, section, field, ctx)`` for every field of every existing item."""
    for section in load_schema()["sections"]:
        sid = section["id"]
        if section["repeatable"] is None:
            contexts = [RuleContext(values, sid)]
        else:
            items = values.get(sid) or []
            contexts = [RuleContext(values, sid, i) for i in range(len(items))]
        for ctx in contexts:
            for field in section["fields"]:
                yield f"{ctx.base}.{field['id']}", section, field, ctx


def missing_required(values: dict[str, Any]) -> list[str]:
    """Paths of visible required fields whose value is missing."""
    missing: list[str] = []
    for path, _section, field, ctx in iter_field_contexts(values):
        if not is_required(field, ctx):
            continue
        if is_missing(field, resolve_path(values, path)):
            missing.append(path)
    return missing
