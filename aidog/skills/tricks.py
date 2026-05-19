from __future__ import annotations

from .. import hardware
from .registry import tool


@tool("handshake", "Offer a paw to shake.", category="trick")
def handshake() -> None:
    hardware.flow().run("handshake")


@tool("high_five", "High-five with a front paw.", category="trick")
def high_five() -> None:
    hardware.flow().run("high five")


@tool("scratch", "Scratch the body with a hind leg.", category="trick")
def scratch() -> None:
    hardware.flow().run("scratch")


@tool("lick_hand", "Lick a hand in front of the snout.", category="trick")
def lick_hand() -> None:
    hardware.flow().run("lick hand")


@tool("feet_shake", "Shake the feet (post-bath dog).", category="trick")
def feet_shake() -> None:
    hardware.flow().run("feet shake")


@tool("surprise", "Startled-surprise reaction.", category="trick")
def surprise() -> None:
    hardware.flow().run("surprise")


@tool("fluster", "Flustered, agitated reaction.", category="trick")
def fluster() -> None:
    hardware.flow().run("fluster")


@tool("doze_off", "Doze off (sleepy lay-down pose).", category="trick")
def doze_off() -> None:
    hardware.flow().run("doze off")
