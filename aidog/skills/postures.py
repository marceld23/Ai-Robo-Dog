from __future__ import annotations

from .. import hardware
from .registry import tool


@tool("sit", "Sit down.", category="posture")
def sit() -> None:
    hardware.flow().run("sit")


@tool("stand", "Stand up on all four legs.", category="posture")
def stand() -> None:
    hardware.flow().run("stand")


@tool("lie_down", "Lie down on the floor.", category="posture")
def lie_down() -> None:
    hardware.flow().run("lie")


@tool("stretch", "Stretch like a dog waking up.", category="posture")
def stretch() -> None:
    hardware.flow().run("stretch")


@tool("push_up", "Do a push-up motion.", category="posture")
def push_up() -> None:
    hardware.flow().run("push up")


@tool("half_sit", "Half-sit posture (alert ready stance).", category="posture")
def half_sit() -> None:
    d = hardware.dog()
    d.do_action("half_sit", speed=70)
    d.wait_all_done()
