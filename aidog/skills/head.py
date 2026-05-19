from __future__ import annotations

from .. import hardware
from .registry import tool


@tool(
    "set_head_pose",
    "Move the head to an absolute yaw/roll/pitch pose in degrees.",
    category="head",
)
def set_head_pose(yaw: float = 0.0, roll: float = 0.0, pitch: float = 0.0) -> None:
    d = hardware.dog()
    d.head_move([[float(yaw), float(roll), float(pitch)]], speed=70)
    d.wait_head_done()
