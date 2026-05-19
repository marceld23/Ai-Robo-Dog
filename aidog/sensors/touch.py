"""Touch-Sensor-Polling-Thread."""
from __future__ import annotations

import logging
import threading
import time

from .. import hardware
from .bus import SensorBus, SensorEvent

log = logging.getLogger(__name__)

POLL_INTERVAL_SEC = 0.05
DEBOUNCE_SEC = 1.0


def _loop(bus: SensorBus) -> None:
    dog = hardware.dog()
    if not dog.dual_touch:
        log.warning("dual_touch not available — touch sensor disabled")
        return
    last_state = "N"
    last_emit = 0.0
    while not bus.stop_signal().is_set():
        try:
            state = dog.dual_touch.read()
        except Exception:
            time.sleep(POLL_INTERVAL_SEC)
            continue
        now = time.monotonic()
        if state != "N" and state != last_state and (now - last_emit) > DEBOUNCE_SEC:
            ev = SensorEvent(kind="touch", payload={"style": state})
            if bus.emit(ev):
                log.debug("touch event emitted: %s", state)
            last_emit = now
        last_state = state
        time.sleep(POLL_INTERVAL_SEC)


def start(bus: SensorBus) -> threading.Thread:
    t = threading.Thread(target=_loop, args=(bus,), name="touch-sensor", daemon=True)
    t.start()
    return t
