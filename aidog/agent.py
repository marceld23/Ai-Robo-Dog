"""
PiDogAgent — bridges LLM tool-calls to the local skill registry.

Phase 2: synchronous, text-input only. Hardware is touched lazily on the first
tool dispatch via the hardware singleton.
"""
from __future__ import annotations

import logging
from typing import Any

from . import skills
from .llm import LLMClient

log = logging.getLogger(__name__)


class PiDogAgent:
    def __init__(self, llm_cfg: dict[str, Any]) -> None:
        self._llm = LLMClient(cfg=llm_cfg, tool_executor=self._dispatch)

    def chat(self, user_text: str, image_b64: str | None = None,
             telemetry: dict[str, Any] | None = None) -> list[str]:
        result = self._llm.run_turn(user_text, image_b64=image_b64,
                                    telemetry=telemetry)
        if result.assistant_content:
            log.debug("(assistant content suppressed): %s", result.assistant_content)
        return [self._format_call(tc) for tc in result.tool_calls]

    def _dispatch(self, name: str, arguments: dict[str, Any]) -> Any:
        try:
            spec = skills.get(name)
        except KeyError as exc:
            return f"error: {exc}"
        try:
            result = spec.call(**arguments)
        except TypeError as exc:
            return f"error: bad arguments: {exc}"
        # None → "ok" (action tool without a return value), otherwise pass the
        # tool result through (perception tools return dicts, get_camera_image
        # returns the image sentinel).
        return "ok" if result is None else result

    @staticmethod
    def _format_call(tc) -> str:
        args = ", ".join(f"{k}={v!r}" for k, v in tc.arguments.items())
        prefix = "✗" if tc.error else "✓"
        suffix = f"  → {tc.result}" if tc.error or tc.result != "ok" else ""
        return f"  {prefix} {tc.name}({args}){suffix}"

    @property
    def tool_count(self) -> int:
        return self._llm.tool_count
