"""Convert the in-process tool registry into OpenAI Function-Calling tool defs."""
from __future__ import annotations

from typing import Any

from ..skills.registry import ParamSpec, ToolSpec, all_tools

_JSON_TYPE = {
    int: "integer",
    float: "number",
    bool: "boolean",
    str: "string",
}


def _param_schema(p: ParamSpec) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": _JSON_TYPE.get(p.type, "string")}
    if p.choices:
        schema["enum"] = list(p.choices)
    if not p.required:
        schema["default"] = p.default
    return schema


def _tool_to_openai(spec: ToolSpec) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    required: list[str] = []
    for p in spec.params:
        properties[p.name] = _param_schema(p)
        if p.required:
            required.append(p.name)

    parameters: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        parameters["required"] = required

    return {
        "type": "function",
        "function": {
            "name": spec.name,
            "description": spec.description,
            "parameters": parameters,
        },
    }


def tools_to_openai(specs: dict[str, ToolSpec] | None = None) -> list[dict[str, Any]]:
    specs = specs if specs is not None else all_tools()
    return [_tool_to_openai(spec) for spec in specs.values()]
