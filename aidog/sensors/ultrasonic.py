"""Ultraschall-Polling-Thread mit Hysterese."""
from __future__ import annotations

import logging
import threading
import time

from .. import hardware
from .bus import SensorBus, SensorEvent

log = logging.getLogger(__name__)

POLL_INTERVAL_SEC = 0.2
TOO_CLOSE_CM = 10.0
LEAVE_HYSTERESIS_FACTOR = 1.5  # zone verlassen erst bei 1.5× Schwelle


def _loop(bus: SensorBus) -> None:
    in_zone = False
    while not bus.stop_signal().is_set():
        try:
            dist = float(hardware.dog().read_distance())
        except Exception:
            time.sleep(POLL_INTERVAL_SEC)
            continue
        if dist <= 0:  # Sensor liefert -1 oder 0 bei Fehler
            time.sleep(POLL_INTERVAL_SEC)
            continue
        if not in_zone and dist < TOO_CLOSE_CM:
            ev = SensorEvent(
                kind="too_close",
                payload={"distance_cm": round(dist, 1)},
                severity="warn",
            )
            if bus.emit(ev):
                log.debug("too_close emitted: %.1f cm", dist)
            in_zone = True
        elif in_zone and dist >= TOO_CLOSE_CM * LEAVE_HYSTERESIS_FACTOR:
            in_zone = False
        time.sleep(POLL_INTERVAL_SEC)


def start(bus: SensorBus) -> threading.Thread:
    t = threading.Thread(target=_loop, args=(bus,), name="ultrasonic-sensor", daemon=True)
    t.start()
    return t
