"""Validation of model-chosen tool arguments against a *discovered* JSON Schema.

Supports the subset MCP tool schemas use here: object properties, required,
additionalProperties, type, enum, minLength/maxLength, minimum/maximum, pattern.
The schema comes from ``tools/list``; nothing here knows a tool by name.
"""

from __future__ import annotations

import re
from typing import Any, Dict


def _is_type(value: Any, expected: str) -> bool:
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return type(value) is int
    if expected == "number":
        return type(value) in (int, float)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    return True


def validate_arguments(schema: Dict[str, Any], arguments: Any) -> None:
    """Raise ``TypeError``/``ValueError`` with a model-readable message on mismatch."""
    if not isinstance(arguments, dict):
        raise TypeError("Tool arguments must be a JSON object")
    properties = schema.get("properties", {})
    missing = [name for name in schema.get("required", []) if name not in arguments]
    if missing:
        raise ValueError(f"Missing required argument(s): {', '.join(sorted(missing))}")
    if schema.get("additionalProperties") is False:
        unexpected = sorted(set(arguments) - set(properties))
        if unexpected:
            raise ValueError(f"Unexpected argument(s): {', '.join(unexpected)}")
    for key, value in arguments.items():
        rule = properties.get(key)
        if rule is None:
            continue
        expected = rule.get("type")
        if expected and not _is_type(value, expected):
            raise TypeError(f"Argument '{key}' must be {expected}")
        if "enum" in rule and value not in rule["enum"]:
            allowed = ", ".join(map(str, rule["enum"]))
            raise ValueError(f"Argument '{key}' must be one of: {allowed}")
        if isinstance(value, str):
            if "minLength" in rule and len(value.strip()) < rule["minLength"]:
                raise ValueError(f"Argument '{key}' must not be empty")
            if "maxLength" in rule and len(value) > rule["maxLength"]:
                raise ValueError(
                    f"Argument '{key}' must be at most {rule['maxLength']} characters"
                )
            if "pattern" in rule and not re.search(rule["pattern"], value):
                raise ValueError(f"Argument '{key}' does not match the required format")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in rule and value < rule["minimum"]:
                raise ValueError(f"Argument '{key}' must be at least {rule['minimum']}")
            if "maximum" in rule and value > rule["maximum"]:
                raise ValueError(f"Argument '{key}' must be at most {rule['maximum']}")


def normalize_arguments(schema: Dict[str, Any], arguments: Any) -> Any:
    """Coerce integer-typed arguments a model emitted as decimal strings ("5" -> 5)."""
    if not isinstance(arguments, dict):
        return arguments
    normalized = dict(arguments)
    for key, rule in schema.get("properties", {}).items():
        value = normalized.get(key)
        if (
            rule.get("type") == "integer"
            and isinstance(value, str)
            and value.isascii()
            and value.isdecimal()
        ):
            normalized[key] = int(value)
    return normalized
