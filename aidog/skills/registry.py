"""Tool registry: skills register themselves via @tool and become callable by name."""
from __future__ import annotations

import inspect
import logging
import typing
from dataclasses import dataclass, field
from typing import Any, Callable, get_type_hints

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ParamSpec:
    name: str
    type: type
    required: bool
    default: Any = None
    choices: tuple[Any, ...] | None = None


@dataclass(frozen=True)
class ToolSpec:
    name: str
    func: Callable[..., Any]
    description: str
    category: str
    params: tuple[ParamSpec, ...] = field(default_factory=tuple)

    def call(self, **kwargs: Any) -> Any:
        return self.func(**kwargs)


_REGISTRY: dict[str, ToolSpec] = {}


def tool(
    name: str,
    description: str,
    category: str = "misc",
    *,
    choices: dict[str, tuple[Any, ...]] | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator: register a function as an LLM-callable tool."""
    choices = choices or {}

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        sig = inspect.signature(func)
        hints = get_type_hints(func)
        params: list[ParamSpec] = []
        for pname, p in sig.parameters.items():
            ptype = hints.get(pname, str)
            # Unwrap Literal[...] / Optional[...] for the surface type.
            origin = typing.get_origin(ptype)
            if origin is typing.Literal:
                literal_args = typing.get_args(ptype)
                literal_choices = literal_args
                ptype = type(literal_args[0]) if literal_args else str
                params.append(ParamSpec(
                    name=pname,
                    type=ptype,
                    required=p.default is inspect.Parameter.empty,
                    default=None if p.default is inspect.Parameter.empty else p.default,
                    choices=literal_choices,
                ))
                continue
            params.append(ParamSpec(
                name=pname,
                type=ptype,
                required=p.default is inspect.Parameter.empty,
                default=None if p.default is inspect.Parameter.empty else p.default,
                choices=choices.get(pname),
            ))

        if name in _REGISTRY:
            raise ValueError(f"Tool '{name}' already registered")
        _REGISTRY[name] = ToolSpec(
            name=name,
            func=func,
            description=description,
            category=category,
            params=tuple(params),
        )
        return func

    return decorator


def get(name: str) -> ToolSpec:
    if name not in _REGISTRY:
        raise KeyError(f"Unknown tool: {name!r}. Known: {sorted(_REGISTRY)}")
    return _REGISTRY[name]


def all_tools() -> dict[str, ToolSpec]:
    return dict(_REGISTRY)


def by_category() -> dict[str, list[ToolSpec]]:
    out: dict[str, list[ToolSpec]] = {}
    for spec in _REGISTRY.values():
        out.setdefault(spec.category, []).append(spec)
    for specs in out.values():
        specs.sort(key=lambda s: s.name)
    return out


def coerce_kwargs(spec: ToolSpec, raw: dict[str, str]) -> dict[str, Any]:
    """Convert CLI-style string kwargs into the function's declared types."""
    out: dict[str, Any] = {}
    declared = {p.name: p for p in spec.params}
    for k, v in raw.items():
        if k not in declared:
            raise ValueError(f"Tool '{spec.name}' has no parameter '{k}'")
        p = declared[k]
        out[k] = _coerce(v, p.type)
        if p.choices and out[k] not in p.choices:
            raise ValueError(
                f"Parameter '{k}'={out[k]!r} must be one of {list(p.choices)}"
            )
    for p in spec.params:
        if p.required and p.name not in out:
            raise ValueError(f"Tool '{spec.name}' missing required param '{p.name}'")
    return out


def _coerce(value: str, target: type) -> Any:
    if target is bool:
        if value.lower() in ("1", "true", "yes", "y", "on"):
            return True
        if value.lower() in ("0", "false", "no", "n", "off"):
            return False
        raise ValueError(f"Cannot parse {value!r} as bool")
    if target is int:
        return int(value)
    if target is float:
        return float(value)
    return value  # str / fallback
