"""
Perception tools — the LLM actively fetches sensor data.

Each tool returns a dict that is serialized in the agent to a readable `tool`
result and appears as a history entry in the next LLM turn.
"""
from __future__ import annotations

import time
from typing import Any

from .. import config as _cfg, hardware
from .registry import tool


# Zones from config.yaml; fallback to the plan table (§ 5.6).
_DEFAULT_ZONES = {
    "energetic": 7.8,
    "normal": 7.2,
    "tired": 6.8,
    "sleepy": 6.4,
    "exhausted": 6.0,
    "critical": 5.8,
}
# 0 % at empty battery (6.0 V), 100 % at full 18650 cells (8.4 V).
_BATT_EMPTY_V = 6.0
_BATT_FULL_V = 8.4

_ABNORMAL_TILT_DEG = 30.0


# Public re-exports for aidog.web.server.get_telemetry()
__all__ = ["_battery_zone", "_battery_percent", "_DEFAULT_ZONES",
           "_ABNORMAL_TILT_DEG"]


def _battery_zone(voltage: float, zones: dict[str, float] | None = None) -> str:
    z = zones or _DEFAULT_ZONES
    # Sort descending: highest threshold first, first match wins.
    for name, thr in sorted(z.items(), key=lambda kv: -kv[1]):
        if voltage >= thr:
            return name
    return "critical"


def _battery_percent(voltage: float) -> int:
    pct = (voltage - _BATT_EMPTY_V) / (_BATT_FULL_V - _BATT_EMPTY_V) * 100
    return max(0, min(100, int(round(pct))))


@tool("read_distance",
      "Distance from the ultrasonic sensor on the snout, in cm. Returns "
      "{distance_cm: null} when the sensor got no echo (no obstacle within "
      "range, or sensor not facing one) — do not assume a value then.",
      category="perception")
def read_distance() -> dict[str, Any]:
    cm = float(hardware.dog().read_distance())
    return {"distance_cm": round(cm, 1) if cm >= 0 else None}


@tool("read_orientation", "Pitch and roll from the IMU. is_abnormal flags |angle| > 30°.",
      category="perception")
def read_orientation() -> dict[str, Any]:
    d = hardware.dog()
    pitch = float(d.pitch)
    roll = float(d.roll)
    abnormal = abs(pitch) > _ABNORMAL_TILT_DEG or abs(roll) > _ABNORMAL_TILT_DEG
    return {
        "pitch_deg": round(pitch, 1),
        "roll_deg": round(roll, 1),
        "is_abnormal": abnormal,
    }


@tool("read_touch_state", "Current head touch sensor: N=none, L=back, R=front, "
      "LS=back→front slide, RS=front→back slide.", category="perception")
def read_touch_state() -> dict[str, Any]:
    d = hardware.dog()
    state = d.dual_touch.read() if d.dual_touch else "N"
    return {"state": state}


@tool("read_battery", "Battery voltage, energy zone, and rough percentage.",
      category="perception")
def read_battery() -> dict[str, Any]:
    voltage = float(hardware.dog().get_battery_voltage())
    cfg = _cfg.load().section("sensors").get("battery", {}).get("zones") or _DEFAULT_ZONES
    zone = _battery_zone(voltage, cfg)
    return {
        "voltage": round(voltage, 2),
        "zone": zone,
        "percent": _battery_percent(voltage),
    }


_IMAGE_PREFIX = "__IMAGE_B64__:"


@tool("get_camera_image",
      "Take a photo through the dog's snout camera and analyze it. Use this when "
      "the user asks what you see, who's there, or about the environment.",
      category="perception")
def get_camera_image() -> str:
    b64 = hardware.camera_snapshot_b64()
    return f"{_IMAGE_PREFIX}{b64}"


@tool("read_last_sound_direction",
      "Direction of the most recent loud sound (0°=front, 90°=right, 180°=back, "
      "270°=left). age_ms = -1 if nothing currently detected.",
      category="perception")
def read_last_sound_direction() -> dict[str, Any]:
    d = hardware.dog()
    if not d.ears or not d.ears.isdetected():
        return {"angle_deg": -1, "age_ms": -1}
    angle = int(d.ears.read())
    return {"angle_deg": angle, "age_ms": 0}
