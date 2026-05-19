"""
Sound-direction polling thread.

The TR16F064B chip only holds the busy signal LOW briefly (~ms). With just
2-s polling in the telemetry loop we almost always miss it — hence this
50-ms polling thread, which persistently stores the last detected angle +
timestamp in `LATEST` (read by the server for telemetry).

It also emits a `sound_heard` event on the bus (debounced 1 s), so the LLM
can react to a loud sound (turn the head toward it).
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

from .. import hardware
from .bus import SensorBus, SensorEvent

log = logging.getLogger(__name__)

POLL_INTERVAL_SEC = 0.03  # 33 Hz; the hardware pulse is very short (~ms)
DEBOUNCE_SEC = 1.0

LATEST: dict[str, Any] = {"angle_deg": -1, "ts": 0.0}
_lock = threading.Lock()


def _loop(bus: SensorBus) -> None:
    dog = hardware.dog()
    if not getattr(dog, "ears", None):
        log.warning("sound direction sensor not available")
        return
    last_emit = 0.0
    while not bus.stop_signal().is_set():
        try:
            # While Buddy executes tools (= servos rotating), we ignore
            # detections — otherwise the servo noise triggers false
            # sound_heard events and skews the telemetry to the LLM.
            if bus.is_busy():
                time.sleep(POLL_INTERVAL_SEC)
                continue
            if dog.ears.isdetected():
                angle = int(dog.ears.read())
                if 0 <= angle <= 359:
                    with _lock:
                        LATEST["angle_deg"] = angle
                        LATEST["ts"] = time.time()
                    now = time.monotonic()
                    if (now - last_emit) > DEBOUNCE_SEC:
                        bus.emit(SensorEvent(
                            kind="sound_heard",
                            payload={"angle_deg": angle},
                        ))
                        last_emit = now
        except Exception:
            time.sleep(POLL_INTERVAL_SEC * 4)
            continue
        time.sleep(POLL_INTERVAL_SEC)


def get_latest() -> dict[str, Any]:
    with _lock:
        return dict(LATEST)


def start(bus: SensorBus) -> threading.Thread:
    t = threading.Thread(target=_loop, args=(bus,),
                         name="sound-direction-sensor", daemon=True)
    t.start()
    return t
