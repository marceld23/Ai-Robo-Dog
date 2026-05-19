"""Importing this package triggers registration of every skill via @tool."""
from . import locomotion  # noqa: F401
from . import postures    # noqa: F401
from . import vocal       # noqa: F401
from . import expressions # noqa: F401
from . import tricks      # noqa: F401
from . import head        # noqa: F401
from . import mood        # noqa: F401
from . import perception  # noqa: F401
from . import memory      # noqa: F401
from .registry import (
    ToolSpec,
    all_tools,
    by_category,
    coerce_kwargs,
    get,
    tool,
)

__all__ = [
    "ToolSpec",
    "all_tools",
    "by_category",
    "coerce_kwargs",
    "get",
    "tool",
]
