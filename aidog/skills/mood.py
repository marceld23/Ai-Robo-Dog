from __future__ import annotations

from typing import Literal

from ..led import get_controller
from .registry import tool

Mood = Literal[
    "happy", "playful", "love", "curious", "alert",
    "angry", "scared", "sad", "sleepy",
]


@tool(
    "set_mood",
    "Set the dog's visible mood via the chest LED strip. Mood persists until changed.",
    category="mood",
)
def set_mood(mood: Mood) -> None:
    get_controller().set_mood(mood)
