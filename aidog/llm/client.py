"""
Thin OpenAI-Chat-Completions wrapper for tool-calling.

Knows nothing about the dog — the caller passes a `tool_executor(name, args) -> str`
that runs the actual side effects. This lets us unit-test the LLM loop without
hardware.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Callable

from openai import OpenAI

from ..memory import MemoryStore
from .prompt import get_system_prompt
from .schema import tools_to_openai

log = logging.getLogger(__name__)

_IMAGE_PREFIX = "__IMAGE_B64__:"


@dataclass(frozen=True)
class ToolCallRecord:
    name: str
    arguments: dict[str, Any]
    result: str
    error: bool = False


@dataclass
class TurnResult:
    tool_calls: list[ToolCallRecord]
    assistant_content: str  # ignored per persona, kept for debug logging
    iterations: int


class LLMClient:
    def __init__(
        self,
        cfg: dict[str, Any],
        tool_executor: Callable[[str, dict[str, Any]], str],
        api_key: str | None = None,
    ) -> None:
        self._cfg = cfg
        self._exec = tool_executor
        self._client = OpenAI(api_key=api_key or os.environ.get("OPENAI_API_KEY"))
        self._tools = tools_to_openai()
        self._history: list[dict[str, Any]] = []
        self._max_history_turns = int(cfg.get("max_history_turns", 20))
        self._max_iterations = int(cfg.get("max_tool_iterations", 8))
        self._model = cfg.get("model", "gpt-4o-mini")
        self._vision_model = cfg.get("vision_model", "gpt-4o")
        self._tool_choice = cfg.get("tool_choice", "required")
        self._temperature = float(cfg.get("temperature", 0.7))
        self._needs_vision = False
        self._stop_check: Callable[[], bool] = lambda: False  # injectable
        # Optional event hook: receives (kind: str, payload: dict). Set by the
        # WebServer to broadcast the LLM iterations + tool calls live to the
        # web UI.
        self._event_hook: Callable[[str, dict[str, Any]], None] | None = None

    def set_stop_check(self, fn: Callable[[], bool]) -> None:
        self._stop_check = fn

    def set_event_hook(self, fn: Callable[[str, dict[str, Any]], None]) -> None:
        self._event_hook = fn

    def _emit(self, kind: str, payload: dict[str, Any]) -> None:
        if self._event_hook:
            try:
                self._event_hook(kind, payload)
            except Exception as exc:
                log.warning("event hook failed (%s): %s", kind, exc)

    @property
    def tool_count(self) -> int:
        return len(self._tools)

    def reset_history(self) -> None:
        self._history.clear()

    def run_turn(self, user_text: str, image_b64: str | None = None,
                 telemetry: dict[str, Any] | None = None) -> TurnResult:
        self._latest_telemetry = telemetry  # for system-prompt inject
        if image_b64:
            self._history.append({"role": "user", "content": [
                {"type": "text", "text": user_text},
                {"type": "image_url", "image_url": {
                    "url": f"data:image/jpeg;base64,{image_b64}",
                    "detail": "low",
                }},
            ]})
            self._needs_vision = True
        else:
            self._history.append({"role": "user", "content": user_text})
        self._trim_history()

        tool_calls_record: list[ToolCallRecord] = []
        assistant_content = ""

        for iteration in range(1, self._max_iterations + 1):
            if self._stop_check():
                log.info("LLM loop aborted by stop_check at iter %d", iteration)
                return TurnResult(
                    tool_calls=tool_calls_record,
                    assistant_content=assistant_content,
                    iterations=iteration,
                )
            tool_choice = self._tool_choice if iteration == 1 else "auto"
            system_msgs = [{"role": "system", "content": get_system_prompt()}]
            mem_text = MemoryStore.instance().render_for_prompt()
            if mem_text:
                system_msgs.append({"role": "system", "content": mem_text})
            tlm = getattr(self, "_latest_telemetry", None)
            if tlm:
                tlm_lines = ["Aktuelle Sensor-Werte:"]
                if tlm.get("distance_cm") is not None:
                    tlm_lines.append(f"  vorne Hindernis-Distanz: {tlm['distance_cm']} cm")
                else:
                    tlm_lines.append("  vorne Hindernis-Distanz: unbekannt (kein Echo)")
                if tlm.get("pitch_deg") is not None:
                    tlm_lines.append(
                        f"  Körper-Neigung: pitch={tlm['pitch_deg']}° "
                        f"roll={tlm['roll_deg']}°"
                        + (" (anormal!)" if tlm.get("tilt_abnormal") else "")
                    )
                if tlm.get("battery_v") is not None:
                    tlm_lines.append(
                        f"  Akku: {tlm['battery_v']} V "
                        f"({tlm.get('battery_zone')}, {tlm.get('battery_percent')} %)"
                    )
                if tlm.get("sound_age_ms", -1) >= 0 and tlm["sound_age_ms"] < 5000:
                    tlm_lines.append(
                        f"  letztes Geräusch: aus {tlm['sound_angle_deg']}° "
                        f"vor {tlm['sound_age_ms']} ms (0°=vorn, 90°=rechts, "
                        f"180°=hinten, 270°=links)"
                    )
                system_msgs.append({"role": "system",
                                    "content": "\n".join(tlm_lines)})
            messages = [*system_msgs, *self._history]

            model = self._vision_model if self._needs_vision else self._model
            self._needs_vision = False
            log.debug("LLM call (iter %d, %d msgs, model=%s)", iteration, len(messages), model)
            self._emit("llm_iteration", {
                "iteration": iteration,
                "model": model,
                "messages_count": len(messages),
            })
            response = self._client.chat.completions.create(
                model=model,
                messages=messages,
                tools=self._tools,
                tool_choice=tool_choice,
                temperature=self._temperature,
            )
            choice = response.choices[0]
            msg = choice.message

            assistant_msg: dict[str, Any] = {"role": "assistant"}
            if msg.content:
                assistant_content = msg.content
                assistant_msg["content"] = msg.content
                log.debug("(assistant content ignored): %s", msg.content)
            if msg.tool_calls:
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in msg.tool_calls
                ]
            # Empty assistant messages (neither content nor tool_calls) are
            # rejected by OpenAI on the next call with a 400 — so drop them.
            if msg.content or msg.tool_calls:
                self._history.append(assistant_msg)

            if not msg.tool_calls:
                return TurnResult(
                    tool_calls=tool_calls_record,
                    assistant_content=assistant_content,
                    iterations=iteration,
                )

            for tc in msg.tool_calls:
                name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError as exc:
                    args = {}
                    result_text = f"error: invalid JSON arguments: {exc}"
                    err = True
                else:
                    try:
                        result = self._exec(name, args)
                        result_text = result if isinstance(result, str) else json.dumps(result)
                        err = False
                    except Exception as exc:  # noqa: BLE001 — surface to LLM
                        log.exception("Tool %s(%s) raised", name, args)
                        result_text = f"error: {exc}"
                        err = True

                # Sentinel: tool returns an image → tool message with a marker,
                # plus a user-content block with the image before the next LLM
                # call. GPT-4o (vision) is selected automatically.
                if not err and result_text.startswith(_IMAGE_PREFIX):
                    b64 = result_text[len(_IMAGE_PREFIX):]
                    record_text = "(camera image attached)"
                    tool_calls_record.append(
                        ToolCallRecord(name=name, arguments=args, result=record_text, error=False)
                    )
                    self._history.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": "Camera image attached as next user message.",
                    })
                    self._history.append({
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "(camera snapshot)"},
                            {"type": "image_url", "image_url": {
                                "url": f"data:image/jpeg;base64,{b64}",
                                "detail": "low",
                            }},
                        ],
                    })
                    self._needs_vision = True
                    continue

                tool_calls_record.append(
                    ToolCallRecord(name=name, arguments=args, result=result_text, error=err)
                )
                self._emit("llm_tool_call", {
                    "iteration": iteration,
                    "name": name,
                    "args": args,
                    "result": result_text[:200],
                    "error": err,
                })
                self._history.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_text,
                })

            if choice.finish_reason == "stop" and not msg.tool_calls:
                break

        log.warning("Hit max_tool_iterations=%d without stop", self._max_iterations)
        return TurnResult(
            tool_calls=tool_calls_record,
            assistant_content=assistant_content,
            iterations=self._max_iterations,
        )

    def _trim_history(self) -> None:
        # Keep the last N user turns plus everything after them. A "turn" is one
        # user message and its trailing assistant/tool messages.
        user_idx = [i for i, m in enumerate(self._history) if m.get("role") == "user"]
        if len(user_idx) <= self._max_history_turns:
            return
        cut = user_idx[-self._max_history_turns]
        dropped = cut
        self._history = self._history[cut:]
        log.debug("Trimmed %d old history messages", dropped)
