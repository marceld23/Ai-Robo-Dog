"""
Threading-based sensor event bus.

Sensors run as daemon threads and write `SensorEvent` objects into a central
queue. While the consumer (listen loop) is busy, sensors drop new events
(instead of queuing them) — this prevents a backlog of petting or distance
events while an LLM turn is running. A self-debounce per sensor ensures that
no event flood arrives even in the idle state.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Literal

log = logging.getLogger(__name__)

EventKind = Literal["wake", "touch", "too_close", "tilt_abnormal", "fall",
                    "sound_heard", "battery_zone_change"]


@dataclass(frozen=True)
class SensorEvent:
    kind: EventKind
    payload: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)
    severity: Literal["info", "warn", "critical"] = "info"


class SensorBus:
    _instance: "SensorBus | None" = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._queue: queue.Queue[SensorEvent] = queue.Queue()
        self._busy = threading.Event()  # cleared = idle, set = busy
        self._stop = threading.Event()

    @classmethod
    def instance(cls) -> "SensorBus":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def emit(self, event: SensorEvent) -> bool:
        """Drop event when bus is busy. Returns True if accepted."""
        if self._busy.is_set():
            return False
        self._queue.put(event)
        return True

    def emit_force(self, event: SensorEvent) -> None:
        """For critical events that must be queued even during busy."""
        self._queue.put(event)

    def get(self, timeout: float | None = None) -> SensorEvent | None:
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def is_busy(self) -> bool:
        return self._busy.is_set()

    def set_busy(self) -> None:
        self._busy.set()

    def set_idle(self) -> None:
        self._busy.clear()

    def stop_signal(self) -> threading.Event:
        return self._stop

    def shutdown(self) -> None:
        self._stop.set()
