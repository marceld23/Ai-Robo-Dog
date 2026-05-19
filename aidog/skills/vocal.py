from __future__ import annotations

import os
import random
import subprocess
import time

from .. import hardware
from .registry import tool

_SOUND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sounds")


def _play(name: str) -> None:
    """pidog.speak_block hangs in the pygame path once the 12 servo/sensor
    threads are running — paplay via PipeWire-Pulse bypasses that reliably."""
    for ext in (".mp3", ".wav"):
        path = os.path.join(_SOUND_DIR, name + ext)
        if os.path.isfile(path):
            subprocess.run(["paplay", path], check=False)
            return
    raise FileNotFoundError(f"sound not found: {name}")


def _bark_with(sound: str) -> None:
    d = hardware.dog()
    d.head_move([[0, 0, 25]], immediately=True, speed=100)
    d.wait_head_done()
    _play(sound)
    d.head_move([[0, 0, 0]], immediately=True, speed=100)
    d.wait_head_done()


@tool("bark_once", "Single bark.", category="vocal")
def bark_once() -> None:
    _bark_with(random.choice(["single_bark_1", "single_bark_2"]))


@tool("bark_aggressive", "Multiple sharp barks.", category="vocal")
def bark_aggressive(times: int = 3) -> None:
    for i in range(max(1, times)):
        _bark_with("single_bark_1" if i % 2 == 0 else "single_bark_2")
        time.sleep(0.1)


@tool("growl", "Low growl (warning).", category="vocal")
def growl() -> None:
    _play(random.choice(["growl_1", "growl_2"]))


@tool("howl", "Howl (long, mournful).", category="vocal")
def howl() -> None:
    hardware.flow().run("howling")


@tool("whine_confused", "Confused whining with a tilted head.", category="vocal")
def whine_confused() -> None:
    d = hardware.dog()
    d.do_action("tilting_head_left", speed=80)
    _play(random.choice(["confused_1", "confused_2", "confused_3"]))
    d.wait_all_done()


@tool("pant", "Panting sound and motion.", category="vocal")
def pant() -> None:
    hardware.flow().run("pant")


@tool("snore", "Snore (eyes-closed, lying down).", category="vocal")
def snore() -> None:
    hardware.flow().run("lie")
    _play("snoring")


@tool("woohoo_excited", "Excited whoop with tail wag.", category="vocal")
def woohoo_excited() -> None:
    d = hardware.dog()
    d.do_action("wag_tail", speed=100)
    _play("woohoo")
    d.tail_stop()


@tool("angry_grunt", "Short angry grunt.", category="vocal")
def angry_grunt() -> None:
    _play("angry")


@tool("silent", "Deliberate silence (no-op).", category="vocal")
def silent() -> None:
    return None
