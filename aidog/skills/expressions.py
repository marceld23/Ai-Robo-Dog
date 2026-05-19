from __future__ import annotations

import time
from typing import Literal

from .. import hardware
from .registry import tool


@tool("wag_tail", "Wag the tail. intensity 1-3 controls how long.", category="expression")
def wag_tail(intensity: int = 2) -> None:
    intensity = max(1, min(3, int(intensity)))
    hardware.flow().run("wag tail")
    time.sleep(0.5 * intensity)
    hardware.dog().tail_stop()


@tool("shake_head", "Shake the head left-right (dog disagreement).", category="expression")
def shake_head() -> None:
    hardware.flow().run("shake head")


@tool("tilt_head", "Tilt head curiously to one side.", category="expression")
def tilt_head(direction: Literal["left", "right"] = "left") -> None:
    d = hardware.dog()
    d.do_action(f"tilting_head_{direction}", speed=80)
    d.wait_all_done()


@tool("nod", "Nod the head up and down (yes).", category="expression")
def nod() -> None:
    hardware.flow().run("nod")


@tool("look_around", "Sweep head left-right scanning the surroundings.", category="expression")
def look_around() -> None:
    d = hardware.dog()
    for yaw in (-45, 0, 45, 0, -45, 0):
        d.head_move([[yaw, 0, 0]], speed=60)
        d.wait_head_done()
