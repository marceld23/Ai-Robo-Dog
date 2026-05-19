"""
Wake word in a thread — wraps `aidog.audio.wake.WakeWord` and emits a
`SensorEvent(kind="wake")` onto the bus. Pauses while the bus is busy
(otherwise its arecord would collide with the recording arecord).
"""
from __future__ import annotations

import logging
import threading
import time

from ..audio.wake import WakeWord
from .bus import SensorBus, SensorEvent

log = logging.getLogger(__name__)


def _loop(wake: WakeWord, bus: SensorBus) -> None:
    while not bus.stop_signal().is_set():
        while bus.is_busy() and not bus.stop_signal().is_set():
            time.sleep(0.1)
        if bus.stop_signal().is_set():
            break
        try:
            phrase = wake.wait_for_wake()
        except Exception as exc:
            log.warning("wake loop error: %s", exc)
            time.sleep(0.5)
            continue
        bus.emit_force(SensorEvent(kind="wake", payload={"phrase": phrase}))
        # Wait until the consumer has picked up the wake (busy set),
        # otherwise wake.wait_for_wake() restarts immediately and the audio
        # device gets two arecord spawns in parallel.
        for _ in range(20):
            if bus.is_busy() or bus.stop_signal().is_set():
                break
            time.sleep(0.05)


def start(wake: WakeWord, bus: SensorBus) -> threading.Thread:
    t = threading.Thread(target=_loop, args=(wake, bus), name="wake-sensor", daemon=True)
    t.start()
    return t
