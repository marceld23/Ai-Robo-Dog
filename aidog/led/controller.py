"""
LED-strip controller.

Mood (from the LLM via `set_mood`) and lifecycle (from the listen loop via
`set_lifecycle`) are stored separately. The effective display results from
the priority:

    error  >  battery_low  >  lifecycle (listening/thinking/wake/sleeping)
                           >  mood  >  default-idle (breath/white)

As soon as a higher override goes away, the next lower one lights up
automatically.
"""
from __future__ import annotations

import logging
import threading
from typing import Any

from .. import hardware

log = logging.getLogger(__name__)


# Lifecycle specs. `None` = transparent (mood/default applies).
_LIFECYCLE_SPECS: dict[str, dict[str, Any] | None] = {
    "idle":           None,
    # Wake cue: short cyan flash, signals "word detected, wait a moment".
    "wake":           {"style": "boom",          "color": "cyan",   "bps": 2.0},
    # Listening = GREEN: the user may speak now. Clearly distinct from wake.
    "listening":      {"style": "listen",        "color": "green",  "bps": 1.5},
    # Thinking = yellow: STT/LLM is running, do not talk.
    "thinking":       {"style": "listen",        "color": "yellow", "bps": 1.5},
    "error":          {"style": "monochromatic", "color": "red",    "bps": 0},
    "battery_low":    {"style": "breath",        "color": "red",    "bps": 0.5},
    "sleeping":       {"style": "monochromatic", "color": "black",  "bps": 0},
    # Pause: clearly visible, slowly fades in/out.
    "paused":         {"style": "breath",        "color": "magenta", "bps": 0.4},
}

# Once lifecycle is in one of these states, it takes precedence over mood.
_OVERRIDE_LIFECYCLES = {"wake", "listening", "thinking",
                        "error", "battery_low", "sleeping", "paused"}

_DEFAULT_IDLE_SPEC = {"style": "breath", "color": "white", "bps": 0.3}


class LedController:
    def __init__(self, moods: dict[str, dict[str, Any]] | None = None,
                 default_brightness: float = 1.0) -> None:
        self._moods = moods or {}
        self._brightness = float(default_brightness)
        self._current_mood: str | None = None
        self._current_lifecycle: str = "idle"
        self._lock = threading.Lock()

    def set_mood(self, mood: str) -> None:
        if mood not in self._moods:
            raise ValueError(f"Unknown mood {mood!r}. Known: {sorted(self._moods)}")
        with self._lock:
            self._current_mood = mood
            self._apply_locked()
        log.info("LED mood set to %s", mood)

    def set_lifecycle(self, state: str) -> None:
        if state not in _LIFECYCLE_SPECS:
            raise ValueError(f"Unknown lifecycle state {state!r}. "
                             f"Known: {sorted(_LIFECYCLE_SPECS)}")
        with self._lock:
            self._current_lifecycle = state
            self._apply_locked()
        log.debug("LED lifecycle → %s", state)

    def set_brightness(self, brightness: float) -> None:
        with self._lock:
            self._brightness = max(0.0, min(1.0, float(brightness)))
            self._apply_locked()

    def off(self) -> None:
        with self._lock:
            self._current_mood = None
            self._current_lifecycle = "sleeping"
            self._apply_locked()

    def _apply_locked(self) -> None:
        # Compute the effective spec: lifecycle-override > mood > default-idle
        if self._current_lifecycle in _OVERRIDE_LIFECYCLES:
            spec = _LIFECYCLE_SPECS[self._current_lifecycle] or _DEFAULT_IDLE_SPEC
        elif self._current_mood and self._current_mood in self._moods:
            spec = self._moods[self._current_mood]
        else:
            spec = _DEFAULT_IDLE_SPEC
        hardware.dog().rgb_strip.set_mode(
            style=spec.get("style", "breath"),
            color=spec.get("color", "white"),
            bps=float(spec.get("bps", 1.0)),
            brightness=self._brightness,
        )

    @property
    def current_mood(self) -> str | None:
        return self._current_mood

    @property
    def current_lifecycle(self) -> str:
        return self._current_lifecycle

    @property
    def known_moods(self) -> list[str]:
        return sorted(self._moods)


_controller: LedController | None = None


def configure(led_cfg: dict[str, Any]) -> LedController:
    global _controller
    _controller = LedController(
        moods=led_cfg.get("moods", {}),
        default_brightness=float(led_cfg.get("default_brightness", 1.0)),
    )
    return _controller


def get_controller() -> LedController:
    if _controller is None:
        raise RuntimeError("LedController not configured. Call led.configure(cfg) first.")
    return _controller
