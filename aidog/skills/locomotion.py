from __future__ import annotations

import logging

from .. import hardware
from .registry import tool

log = logging.getLogger(__name__)


# Pidog's default speed for the walk actions is 98 (near the max). For turns
# this causes tipping forward. Reduced to 80 — smooth enough for continuous
# step sequences, but stable. Pre-stabilize ONLY once per tool call (center
# the head), not between steps — otherwise it looks stuttery.
_TURN_SPEED = 80


def _walk_sequence(action: str, steps: int, speed: int) -> None:
    d = hardware.dog()
    d.head_move([[0, 0, 0]], immediately=True, speed=80)
    for _ in range(max(1, steps)):
        d.do_action(action, speed=speed)
        d.wait_all_done()


@tool("walk_forward", "Walk forward for N steps.", category="locomotion")
def walk_forward(steps: int = 1) -> None:
    _walk_sequence("forward", steps, _TURN_SPEED)


@tool("walk_backward", "Walk backward for N steps.", category="locomotion")
def walk_backward(steps: int = 1) -> None:
    _walk_sequence("backward", steps, _TURN_SPEED)


@tool("turn_left", "Turn the body to the left for N steps.", category="locomotion")
def turn_left(steps: int = 1) -> None:
    _walk_sequence("turn_left", steps, _TURN_SPEED)


@tool("turn_right", "Turn the body to the right for N steps.", category="locomotion")
def turn_right(steps: int = 1) -> None:
    _walk_sequence("turn_right", steps, _TURN_SPEED)


@tool("trot", "Light trotting forward for N steps.", category="locomotion")
def trot(steps: int = 2) -> None:
    d = hardware.dog()
    for _ in range(max(1, steps)):
        d.do_action("trot", speed=95)
    d.wait_all_done()


@tool("stop", "Stop all movement immediately.", category="locomotion")
def stop() -> None:
    d = hardware.dog()
    d.body_stop()
