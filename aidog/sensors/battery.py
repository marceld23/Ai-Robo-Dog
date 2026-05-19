"""
Battery polling thread with running average and zone-change detection.

Servo loads cause brief voltage drops; without averaging the dog would
constantly jump between zones. We average over N samples and only report real
zone changes as a `battery_zone_change` event on the bus.

The critical shutdown runs directly in the sensor thread (not via the LLM
loop), so that a stuck bus consumer cannot prevent the dog from lying down.
"""
from __future__ import annotations

import logging
import threading
import time

from .. import config as _cfg, hardware, log as log_module
from ..led import controller as led_controller
from .bus import SensorBus, SensorEvent

log = logging.getLogger(__name__)

POLL_INTERVAL_SEC = 30.0
AVERAGE_WINDOW = 10  # 10×30s = 5 min smoothing window against servo load spikes
CRITICAL_CONSECUTIVE_NEEDED = 3  # 3×30s = 90s critical before we shut down
# Values below this threshold are measurement glitches (servo load briefly
# pulls the ADC down to 0). Even completely empty 18650 cells still deliver
# >5 V, anything below that is not real and is discarded.
MIN_VALID_VOLTAGE = 5.0

_DEFAULT_ZONES = {
    "energetic": 7.8,
    "normal": 7.2,
    "tired": 6.8,
    "sleepy": 6.4,
    "exhausted": 6.0,
    "critical": 5.8,
}
# Zones in which the LED switches to "battery_low" (red breathing) and the
# LED controller reduces the global brightness.
_DIM_ZONES = {"tired", "sleepy", "exhausted", "critical"}
_DIM_BRIGHTNESS = 0.5

# Hysteresis: a zone change down (to the lower one) only happens at this much
# BELOW the threshold, so servo spikes do not trigger phantom changes.
_HYSTERESIS_V = 0.05


def _zone_for(voltage: float, zones: dict[str, float]) -> str:
    for name, thr in sorted(zones.items(), key=lambda kv: -kv[1]):
        if voltage >= thr:
            return name
    return "critical"


def _running_average(samples: list[float], new: float) -> float:
    samples.append(new)
    if len(samples) > AVERAGE_WINDOW:
        samples.pop(0)
    return sum(samples) / len(samples)


def _critical_shutdown() -> None:
    """Last action: lie down, LED off, close Pidog cleanly, terminate process."""
    import os
    log.critical("BATTERY CRITICAL — controlled shutdown")
    try:
        leds = led_controller.get_controller()
        leds.set_lifecycle("battery_low")
        leds.set_brightness(0.2)
    except Exception:
        pass
    try:
        d = hardware.dog()
        d.do_action("lie", speed=60)
        d.wait_all_done()
    except Exception as exc:
        log.error("lie-down on shutdown failed: %s", exc)
    try:
        leds = led_controller.get_controller()
        leds.off()
    except Exception:
        pass
    hardware.shutdown()
    os._exit(0)


def _loop(bus: SensorBus, zones: dict[str, float]) -> None:
    samples: list[float] = []
    current_zone: str | None = None
    critical_streak = 0  # consecutive critical samples — shutdown only at CRITICAL_CONSECUTIVE_NEEDED
    leds = led_controller.get_controller()
    while not bus.stop_signal().is_set():
        try:
            v = float(hardware.dog().get_battery_voltage())
        except Exception as exc:
            log.warning("battery read failed: %s", exc)
            time.sleep(POLL_INTERVAL_SEC)
            continue
        # Don't even add an outlier glitch (e.g. 0 V from a servo load spike)
        # to the sample window — otherwise a single 0-V sample pulls the
        # 10-sample average down by 0.75 V and triggers false-positive zones.
        if v < MIN_VALID_VOLTAGE:
            log.debug("battery glitch ignored: %.2f V (below %.1f V threshold)",
                      v, MIN_VALID_VOLTAGE)
            time.sleep(POLL_INTERVAL_SEC)
            continue
        avg = _running_average(samples, v)
        zone = _zone_for(avg, zones)

        # Spike protection for critical: only actually shut down after several
        # consecutive samples. A single servo-load-spike drop does not yet
        # trigger a sleep.
        if zone == "critical":
            critical_streak += 1
        else:
            critical_streak = 0

        # Hysteresis: only change when the avg voltage is far enough below
        # the threshold of the NEW zone (protection against spikes).
        if current_zone is not None and zone != current_zone:
            cur_thr = zones.get(current_zone, 0)
            if avg > cur_thr - _HYSTERESIS_V and zone < current_zone:
                # Backwards (fuller → emptier) too early — spike, ignore.
                pass
            else:
                log.info("battery zone %s → %s (%.2f V)", current_zone, zone, avg)
                bus.emit_force(SensorEvent(
                    kind="battery_zone_change",
                    payload={"voltage": round(avg, 2),
                             "zone": zone,
                             "previous": current_zone},
                    severity="critical" if zone == "critical" else "warn",
                ))
                _apply_zone_to_leds(leds, zone)
                current_zone = zone
        elif current_zone is None:
            current_zone = zone
            log.info("battery initial zone: %s (%.2f V)", zone, avg)
            _apply_zone_to_leds(leds, zone)

        # Critical-shutdown gate — runs every tick, not only on zone change.
        if zone == "critical":
            if critical_streak >= CRITICAL_CONSECUTIVE_NEEDED:
                _critical_shutdown()
                return
            log.warning("critical sample %d/%d (%.2f V) — waiting for confirmation",
                        critical_streak, CRITICAL_CONSECUTIVE_NEEDED, avg)

        time.sleep(POLL_INTERVAL_SEC)


def _apply_zone_to_leds(leds, zone: str) -> None:
    if zone in _DIM_ZONES:
        leds.set_brightness(_DIM_BRIGHTNESS)
        # Override lifecycle only at lower levels, otherwise the normal
        # voice-loop lifecycle (idle/listening/...) stays visible.
        if zone in {"sleepy", "exhausted"}:
            leds.set_lifecycle("battery_low")
    else:
        leds.set_brightness(1.0)


def start(bus: SensorBus) -> threading.Thread:
    cfg = _cfg.load().section("sensors").get("battery") or {}
    zones = cfg.get("zones") or _DEFAULT_ZONES
    t = threading.Thread(target=_loop, args=(bus, zones),
                         name="battery-sensor", daemon=True)
    t.start()
    return t
