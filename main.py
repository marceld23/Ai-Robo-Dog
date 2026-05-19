#!/usr/bin/env python3
"""
aidog CLI.

Usage:
    python main.py list                 # list every registered tool
    python main.py describe <name>      # show one tool's params
    python main.py call <name> [k=v...] # invoke a tool by name
    python main.py sequence <name>...   # call several tools in order
    python main.py chat                 # REPL: type to talk to the dog (Phase 2)
    python main.py chat --say "text"    # one-shot turn, prints tool calls
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Ensure the package is importable when running `python main.py` from anywhere.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from aidog import config as cfg_module
from aidog import hardware, log as log_module
from aidog.agent import PiDogAgent
from aidog.led import controller as led_controller
from aidog import skills  # noqa: F401 — side effect: registers all tools


def _parse_kv(items: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise SystemExit(f"Expected key=value, got: {item!r}")
        k, v = item.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def cmd_list(_args: argparse.Namespace) -> int:
    grouped = skills.by_category()
    for category in sorted(grouped):
        print(f"\n[{category}]")
        for spec in grouped[category]:
            params = ", ".join(
                f"{p.name}: {_type_label(p)}" + ("" if p.required else f" = {p.default!r}")
                for p in spec.params
            )
            print(f"  {spec.name}({params})")
            print(f"    {spec.description}")
    return 0


def cmd_describe(args: argparse.Namespace) -> int:
    spec = skills.get(args.name)
    print(f"{spec.name}  [{spec.category}]")
    print(f"  {spec.description}")
    if not spec.params:
        print("  (no parameters)")
        return 0
    for p in spec.params:
        line = f"  - {p.name}: {_type_label(p)}"
        if not p.required:
            line += f" = {p.default!r}"
        if p.choices:
            line += f"  one of {list(p.choices)}"
        print(line)
    return 0


def cmd_call(args: argparse.Namespace) -> int:
    spec = skills.get(args.name)
    kwargs = skills.coerce_kwargs(spec, _parse_kv(args.kv))
    log = logging.getLogger("aidog.cli")
    log.info("Calling tool %s(%s)", spec.name, kwargs)
    result = spec.call(**kwargs)
    if result is not None:
        print(result)
    return 0


def cmd_sequence(args: argparse.Namespace) -> int:
    log = logging.getLogger("aidog.cli")
    for name in args.names:
        spec = skills.get(name)
        log.info("Calling tool %s()", spec.name)
        result = spec.call()
        if result is not None:
            print(f"  {name} → {result}")
    return 0


def cmd_listen(args: argparse.Namespace) -> int:
    """Wake + sensor bus: 'hey buddy' OR touch/distance trigger Buddy (Phase 6)."""
    config = cfg_module.load()
    audio_cfg = config.section("audio")
    stt_cfg = config.section("stt")
    wake_cfg = config.section("wake")
    agent = PiDogAgent(llm_cfg=config.section("llm"))

    from aidog.audio.recorder import record_until_silence
    from aidog.audio.stt import WhisperSTT, is_likely_hallucination
    from aidog.audio.wake import WakeWord
    from aidog.sensors import battery as battery_sensor
    from aidog.sensors import touch as touch_sensor
    from aidog.sensors import ultrasonic as ultrasonic_sensor
    from aidog.sensors import wake_thread
    from aidog.sensors.bus import SensorBus
    from aidog.skills.vocal import _play

    stt = WhisperSTT(model=stt_cfg.get("model", "whisper-1"),
                     language=stt_cfg.get("language", "de"))
    wake = WakeWord(model_path=wake_cfg.get("model"),
                    phrases=wake_cfg.get("phrases", ["hey buddy"]))
    cue = wake_cfg.get("cue_sound")

    dog = hardware.dog()  # Pidog warm-up (servo init, audio routing)
    leds = led_controller.get_controller()

    def head(yaw: float, roll: float, pitch: float) -> None:
        try:
            dog.head_move([[yaw, roll, pitch]], immediately=True, speed=80)
        except Exception:
            pass

    def snapshot() -> str | None:
        try:
            return hardware.camera_snapshot_b64()
        except Exception as exc:
            logging.getLogger("aidog.cli").warning("camera snapshot failed: %s", exc)
            return None

    def handle_wake(phrase: str) -> None:
        import time as _time
        print(f"[wake={phrase!r}]", flush=True)
        leds.set_lifecycle("wake")
        if cue:
            try:
                _play(cue)
            except Exception as exc:
                logging.getLogger("aidog.cli").warning("wake cue failed: %s", exc)
        # Let the speaker fade out + wake up the mic stream, otherwise the
        # start of the first word is often dead.
        _time.sleep(0.25)
        print("  aufnehmen…", flush=True)
        leds.set_lifecycle("listening")
        rec = record_until_silence(
            max_record_sec=float(audio_cfg.get("max_record_sec", 8)),
            silence_end_sec=float(audio_cfg.get("silence_end_sec", 1.5)),
            min_voice_sec=float(audio_cfg.get("min_voice_sec", 0.3)),
            vad_aggressiveness=int(audio_cfg.get("vad_aggressiveness", 1)),
        )
        head(0, -25, 0)
        leds.set_lifecycle("thinking")
        if not rec.has_voice:
            print(f"  (keine Sprache erkannt, {rec.duration_sec:.1f}s)\n")
            return
        print(f"  {rec.duration_sec:.1f}s aufgenommen → whisper…", flush=True)
        try:
            result = stt.transcribe(rec.wav)
        except Exception as exc:
            print(f"  whisper fehler: {exc}\n")
            return
        print(f"  → {result.text!r}")
        if is_likely_hallucination(result.text):
            print("  (verwerfe Halluzination)\n")
            return
        head(0, 25, 0)
        _render_turn(agent, result.text, image_b64=snapshot())

    def handle_sensor(event) -> None:
        # Sensor event as compact system notation to the LLM, plus current image.
        if event.kind == "touch":
            text = f"<sensor: touch style={event.payload.get('style')}>"
        elif event.kind == "too_close":
            text = f"<sensor: too_close distance={event.payload.get('distance_cm')}cm>"
        elif event.kind == "battery_zone_change":
            text = (f"<sensor: battery_zone_change "
                    f"zone={event.payload.get('zone')} "
                    f"voltage={event.payload.get('voltage')}V "
                    f"previous={event.payload.get('previous')}>")
        else:
            text = f"<sensor: {event.kind} payload={event.payload}>"
        print(f"[{event.kind}] {text}", flush=True)
        leds.set_lifecycle("thinking")
        head(0, 25, 0)
        _render_turn(agent, text, image_b64=snapshot())

    bus = SensorBus.instance()
    threads = [
        wake_thread.start(wake, bus),
        touch_sensor.start(bus),
        ultrasonic_sensor.start(bus),
        battery_sensor.start(bus),
    ]
    print(f"Buddy wartet auf Sprache + Sensor-Events. Ctrl+C zum Beenden.")
    print(f"({agent.tool_count} Tools geladen)\n")
    head(0, 0, 0)
    leds.set_lifecycle("idle")

    try:
        while True:
            event = bus.get(timeout=1.0)
            if event is None:
                continue
            bus.set_busy()
            try:
                if event.kind == "wake":
                    handle_wake(event.payload.get("phrase", "hey buddy"))
                else:
                    handle_sensor(event)
            except Exception as exc:
                logging.getLogger("aidog.cli").exception(
                    "event handler crashed (%s): %s", event.kind, exc)
                leds.set_lifecycle("error")
                import time
                time.sleep(1.5)  # keep error briefly visible
            finally:
                head(0, 0, 0)
                leds.set_lifecycle("idle")
                bus.set_idle()
    except KeyboardInterrupt:
        print()
        return 0
    finally:
        bus.shutdown()


def cmd_web(args: argparse.Namespace) -> int:
    """FastAPI server on :PORT, listen loop runs in a background thread."""
    import uvicorn
    config = cfg_module.load()
    agent = PiDogAgent(llm_cfg=config.section("llm"))

    from aidog.sensors.bus import SensorBus
    from aidog.web.runner import start_worker
    from aidog.web.server import WebServer

    bus = SensorBus.instance()
    leds = led_controller.get_controller()
    server = WebServer(agent=agent, bus=bus, leds=leds)
    start_worker(server)

    print(f"Web-UI läuft auf http://{args.host}:{args.port}")
    print(f"({agent.tool_count} Tools geladen)\n")
    uvicorn.run(server.app, host=args.host, port=args.port, log_level="warning")
    return 0


def cmd_chat(args: argparse.Namespace) -> int:
    config = cfg_module.load()
    agent = PiDogAgent(llm_cfg=config.section("llm"))

    if args.say is not None:
        _render_turn(agent, args.say)
        return 0

    print(f"Buddy is ready. {agent.tool_count} tools loaded.")
    print("Type to talk. Ctrl+D or empty line + Ctrl+C to quit.\n")
    try:
        while True:
            try:
                user = input("you> ").strip()
            except EOFError:
                print()
                return 0
            if not user:
                continue
            _render_turn(agent, user)
    except KeyboardInterrupt:
        print()
        return 0


def _render_turn(agent: PiDogAgent, text: str, image_b64: str | None = None) -> None:
    lines = agent.chat(text, image_b64=image_b64)
    print("[buddy]")
    if not lines:
        print("  (no tool calls)")
    else:
        for line in lines:
            print(line)
    print()


def _type_label(p) -> str:
    if p.choices:
        return "|".join(repr(c) for c in p.choices)
    return p.type.__name__


def _bootstrap() -> None:
    config = cfg_module.load()
    log_module.setup(config.section("logging"))
    hardware.configure(config.section("hardware"))
    led_controller.configure(config.section("led"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aidog", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="List every registered tool").set_defaults(func=cmd_list)

    p_desc = sub.add_parser("describe", help="Describe a single tool")
    p_desc.add_argument("name")
    p_desc.set_defaults(func=cmd_describe)

    p_call = sub.add_parser("call", help="Call a tool by name")
    p_call.add_argument("name")
    p_call.add_argument("kv", nargs="*", help="Parameters as key=value pairs")
    p_call.set_defaults(func=cmd_call)

    p_seq = sub.add_parser("sequence", help="Call several tools by name in order")
    p_seq.add_argument("names", nargs="+")
    p_seq.set_defaults(func=cmd_sequence)

    p_chat = sub.add_parser("chat", help="Talk to the dog via LLM (Phase 2)")
    p_chat.add_argument("--say", help="One-shot turn; prints the dog's tool calls and exits")
    p_chat.set_defaults(func=cmd_chat)

    p_listen = sub.add_parser("listen", help="Push-to-talk via Kopf-Touch (Phase 3)")
    p_listen.set_defaults(func=cmd_listen)

    p_web = sub.add_parser("web", help="Web-UI (Phase 10) auf :8080")
    p_web.add_argument("--host", default="0.0.0.0")
    p_web.add_argument("--port", type=int, default=8080)
    p_web.set_defaults(func=cmd_web)

    args = parser.parse_args(argv)
    _bootstrap()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
