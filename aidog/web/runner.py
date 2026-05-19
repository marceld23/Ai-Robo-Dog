"""
Background worker that runs the wake/sensor/agent loop and emits to the WebServer.

Architecture identical to the CLI `listen` loop, but with additional
`server.emit` calls at every pipeline phase. The stop-soft flag is checked
before every tool loop and interrupts further tool calls (the running tool
finishes).
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

from .. import config as cfg_module, hardware, i18n
from ..agent import PiDogAgent
from ..audio.recorder import record_until_silence
from ..audio.stt import WhisperSTT, is_likely_hallucination
from ..audio.wake import WakeWord
from ..led import controller as led_controller
from ..sensors import battery as battery_sensor
from ..sensors import sound_direction as sound_dir_sensor
from ..sensors import touch as touch_sensor
from ..sensors import ultrasonic as ultrasonic_sensor
from ..sensors import wake_thread
from ..sensors.bus import SensorBus
from ..skills.vocal import _play
from .server import WebServer

log = logging.getLogger(__name__)


def _stop_phrases() -> set[str]:
    """Voice hard-stop phrases for the active language (from config)."""
    cfg = cfg_module.load().get("stop_phrases") or {}
    phrases = cfg.get(i18n.lang()) or cfg.get("en") or ["stop"]
    return {p.strip().lower() for p in phrases}


def _is_stop_command(text: str) -> bool:
    # Whisper often returns punctuation and capitalization — normalize hard.
    norm = text.strip().lower().rstrip(".!?,;:")
    return norm in _stop_phrases()


def run_worker(server: WebServer) -> None:
    config = cfg_module.load()
    audio_cfg = config.section("audio")
    stt_cfg = config.section("stt")
    wake_cfg = config.section("wake")

    _lang = i18n.lang()
    _wake_models = wake_cfg.get("models") or {}
    _wake_model = _wake_models.get(_lang) or _wake_models.get("de")
    stt = WhisperSTT(model=stt_cfg.get("model", "whisper-1"),
                     language=_lang)
    wake = WakeWord(model_path=_wake_model,
                    phrases=wake_cfg.get("phrases", ["hey buddy"]))
    cue = wake_cfg.get("cue_sound")

    dog = hardware.dog()
    leds = server.leds
    agent = server.agent
    bus = server.bus

    # Last head position set by the listen loop. We track it ourselves,
    # because dog.head_current_angles is also changed by LLM tool calls —
    # we want to restore the pose from BEFORE the sensor/wake trigger.
    last_head_pose = [0.0, 0.0, 0.0]

    def head(yaw: float, roll: float, pitch: float) -> None:
        nonlocal last_head_pose
        last_head_pose = [yaw, roll, pitch]
        try:
            dog.head_move([[yaw, roll, pitch]], immediately=True, speed=80)
        except Exception:
            pass

    def head_lean_for_thinking() -> list[float]:
        """Saves the current pose, tilts the head (status display), returns
        the saved pose so the caller can restore it."""
        saved = list(last_head_pose)
        try:
            dog.head_move([[0, 25, 0]], immediately=True, speed=80)
        except Exception:
            pass
        return saved

    def head_restore(pose: list[float]) -> None:
        try:
            dog.head_move([[pose[0], pose[1], pose[2]]],
                          immediately=True, speed=80)
        except Exception:
            pass
        nonlocal last_head_pose
        last_head_pose = list(pose)

    def snapshot() -> str | None:
        try:
            return hardware.camera_snapshot_b64()
        except Exception as exc:
            log.warning("camera snapshot failed: %s", exc)
            return None

    def run_turn(text: str, *, source: str) -> None:
        if server.paused.is_set():
            server.emit("turn_skipped", {"reason": "paused", "text": text, "source": source})
            return
        if server.stop_soft.is_set() or server.stop_hard.is_set():
            server.emit("turn_skipped", {"reason": "stop_requested", "text": text})
            return
        try:
            tlm = server.get_telemetry()
        except Exception as exc:
            log.warning("telemetry fetch failed: %s", exc)
            tlm = None
        # make it visible: what exactly do we send to the LLM?
        server.emit("llm_input", {
            "source": source,
            "text": text,
            "telemetry": tlm,
            "image": True,
        })
        server.emit("turn_start", {"source": source, "text": text})
        leds.set_lifecycle("thinking")
        # Remember head pose + tilt head to the side as a status indicator
        # (also for sensor-triggered requests — user request). After the LLM
        # response, back to the pose before.
        saved_head = head_lean_for_thinking()
        img = snapshot()
        try:
            lines = agent.chat(text, image_b64=img, telemetry=tlm)
        except Exception as exc:
            log.exception("agent.chat failed")
            server.emit("turn_error", {"error": str(exc)})
            head_restore(saved_head)
            return
        server.emit("turn_end", {"tool_calls": lines})
        head_restore(saved_head)

    def handle_wake(phrase: str) -> None:
        server.emit("wake", {"phrase": phrase})
        leds.set_lifecycle("wake")
        if cue:
            try:
                _play(cue)
            except Exception:
                pass
        time.sleep(0.25)
        leds.set_lifecycle("listening")
        server.emit("listening", {})
        rec = record_until_silence(
            max_record_sec=float(audio_cfg.get("max_record_sec", 8)),
            silence_end_sec=float(audio_cfg.get("silence_end_sec", 1.5)),
            min_voice_sec=float(audio_cfg.get("min_voice_sec", 0.3)),
            vad_aggressiveness=int(audio_cfg.get("vad_aggressiveness", 1)),
        )
        # Head left as status: "audio done, going to Whisper"
        try:
            dog.head_move([[0, -25, 0]], immediately=True, speed=80)
        except Exception:
            pass
        leds.set_lifecycle("thinking")
        if not rec.has_voice:
            server.emit("voice_dropped", {"reason": "no_voice", "duration": rec.duration_sec})
            return
        try:
            result = stt.transcribe(rec.wav)
        except Exception as exc:
            server.emit("voice_dropped", {"reason": "whisper_error", "error": str(exc)})
            return
        if is_likely_hallucination(result.text):
            server.emit("voice_dropped", {"reason": "hallucination", "text": result.text})
            return
        server.emit("transcribed", {"text": result.text, "stt_sec": result.duration_sec})
        # Hard stop without LLM on a short stop command
        if _is_stop_command(result.text):
            server.emit("voice_stop", {"text": result.text})
            try:
                dog.body_stop()
                head(0, 0, 0)
                from ..hardware import flow
                flow().run("stand")
            except Exception as exc:
                log.warning("voice-stop neutral pose failed: %s", exc)
            leds.set_lifecycle("idle")
            return
        # On wake: before run_turn set the "position before" to neutral,
        # so Buddy returns there after the LLM response (not to the
        # whisper lean pose).
        last_head_pose[:] = [0.0, 0.0, 0.0]
        run_turn(result.text, source="voice")

    def handle_sensor(event) -> None:
        if event.kind == "touch":
            text = f"<sensor: touch style={event.payload.get('style')}>"
        elif event.kind == "too_close":
            text = f"<sensor: too_close distance={event.payload.get('distance_cm')}cm>"
        elif event.kind == "battery_zone_change":
            text = (f"<sensor: battery_zone_change "
                    f"zone={event.payload.get('zone')} "
                    f"voltage={event.payload.get('voltage')}V "
                    f"previous={event.payload.get('previous')}>")
        elif event.kind == "sound_heard":
            text = f"<sensor: sound_heard angle={event.payload.get('angle_deg')}>"
        elif event.kind == "web_user_message":
            text = event.payload.get("text", "")
        else:
            text = f"<sensor: {event.kind} payload={event.payload}>"
        server.emit("sensor_event", {"kind": event.kind, "payload": event.payload})
        # run_turn remembers the current pose and restores it after the
        # LLM call — Buddy does the status lean and returns to the pose
        # it had before the sensor event.
        run_turn(text, source=event.kind)

    # Start sensor threads
    wake_thread.start(wake, bus)
    touch_sensor.start(bus)
    ultrasonic_sensor.start(bus)
    battery_sensor.start(bus)
    sound_dir_sensor.start(bus)

    server.emit("ready", {"tool_count": agent.tool_count})
    leds.set_lifecycle("idle")

    while not bus.stop_signal().is_set():
        event = bus.get(timeout=1.0)
        if event is None:
            # Reset stop flags in idle (after processing)
            if server.stop_soft.is_set() and not bus.is_busy():
                server.stop_soft.clear()
                server.stop_hard.clear()
            continue
        bus.set_busy()
        try:
            if event.kind == "wake":
                handle_wake(event.payload.get("phrase", "hey buddy"))
            else:
                handle_sensor(event)
        except Exception as exc:
            log.exception("event handler crashed")
            server.emit("error", {"context": event.kind, "error": str(exc)})
            leds.set_lifecycle("error")
            time.sleep(1.5)
        finally:
            # Head position no longer forced to neutral — run_turn does the
            # restore to the pose before the trigger. Keep pause override.
            leds.set_lifecycle("paused" if server.paused.is_set() else "idle")
            bus.set_idle()


def start_worker(server: WebServer) -> threading.Thread:
    t = threading.Thread(target=run_worker, args=(server,),
                         name="aidog-worker", daemon=True)
    t.start()
    return t
