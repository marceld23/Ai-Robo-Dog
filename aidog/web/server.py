"""
FastAPI server for the phase 10 web UI.

Runs in the main process; the listen loop (wake/sensor/agent) runs in a
background thread and pushes events through a thread-safe bridge to all
connected WebSockets. Interactions (user text, direct tool call, stop,
memory CRUD, OpenAI key) come the other way from the WebSocket into the loop.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import queue as queue_mod
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, Response

from .. import i18n, skills
from ..agent import PiDogAgent
from ..memory import MemoryStore
from ..sensors.bus import SensorBus, SensorEvent

log = logging.getLogger(__name__)

_STATIC = Path(__file__).resolve().parent / "static"
_INDEX_HTML = _STATIC / "index.html"


class WebServer:
    def __init__(self, agent: PiDogAgent, bus: SensorBus, leds: Any) -> None:
        self.agent = agent
        self.bus = bus
        self.leds = leds
        self.memory = MemoryStore.instance()

        self.app = FastAPI(title="aidog")
        self._connections: list[WebSocket] = []
        self._connections_lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._event_q: queue_mod.Queue[dict[str, Any]] = queue_mod.Queue()

        self.stop_soft = threading.Event()
        self.stop_hard = threading.Event()
        # Pause switch: sensors keep running, but no LLM call.
        self.paused = threading.Event()

        # Interrupt the LLM loop when stop-soft is pressed — the running tool
        # still finishes, but no new tool call.
        self.agent._llm.set_stop_check(
            lambda: self.stop_soft.is_set() or self.stop_hard.is_set()
        )
        # Live stream of the LLM iterations + tool calls to the web UI.
        self.agent._llm.set_event_hook(self.emit)

        # Memory listener for live updates to the web UI.
        self.memory.add_listener(self._on_memory_changed)

        # Telemetry thread (every 2 s) — started in startup.
        self._telemetry_stop = threading.Event()
        self._telemetry_thread: threading.Thread | None = None
        self._last_sound: dict[str, Any] = {"angle_deg": -1, "ts": 0.0}

        # Camera cache: a snapshot is refreshed at most every 1.5 s.
        self._cam_lock = threading.Lock()
        self._cam_jpeg: bytes | None = None
        self._cam_ts: float = 0.0

        self._setup_routes()

    # --- public API for the listen-loop background thread ---

    def get_telemetry(self) -> dict[str, Any]:
        """Current sensor snapshot for the UI + LLM prompt inject."""
        from .. import hardware
        from ..skills.perception import _battery_zone, _battery_percent, _DEFAULT_ZONES, _ABNORMAL_TILT_DEG
        d = hardware.dog()
        out: dict[str, Any] = {}
        try:
            dist = float(d.read_distance())
            # Pidog returns -1/-2 as an error code (no echo) — treat as
            # unknown, otherwise the LLM considers "it's 1cm in front of me" valid.
            out["distance_cm"] = round(dist, 1) if dist >= 0 else None
        except Exception:
            out["distance_cm"] = None
        try:
            out["pitch_deg"] = round(float(d.pitch), 1)
            out["roll_deg"] = round(float(d.roll), 1)
            out["tilt_abnormal"] = (abs(d.pitch) > _ABNORMAL_TILT_DEG
                                    or abs(d.roll) > _ABNORMAL_TILT_DEG)
        except Exception:
            out["pitch_deg"] = out["roll_deg"] = None
            out["tilt_abnormal"] = False
        try:
            v = float(d.get_battery_voltage())
            # Values <5 V are servo-load-spike glitches, not a real battery value.
            if v < 5.0:
                out["battery_v"] = None
            else:
                out["battery_v"] = round(v, 2)
                out["battery_zone"] = _battery_zone(v, _DEFAULT_ZONES)
                out["battery_percent"] = _battery_percent(v)
        except Exception:
            out["battery_v"] = None
        # Sound direction comes from the 50-ms polling thread (sound_direction.py),
        # not here — the hardware pulse is too short for the 2-s telemetry loop.
        from ..sensors import sound_direction as snd
        latest = snd.get_latest()
        if latest["ts"]:
            out["sound_angle_deg"] = latest["angle_deg"]
            out["sound_age_ms"] = int((time.time() - latest["ts"]) * 1000)
        else:
            out["sound_angle_deg"] = -1
            out["sound_age_ms"] = -1
        out["led_lifecycle"] = self.leds.current_lifecycle
        out["led_mood"] = self.leds.current_mood
        return out

    def get_camera_jpeg(self) -> bytes | None:
        """Cache wrapper around camera_snapshot — refreshed at most every 1.5 s."""
        from .. import hardware
        import base64
        with self._cam_lock:
            if self._cam_jpeg and (time.time() - self._cam_ts) < 1.5:
                return self._cam_jpeg
        try:
            b64 = hardware.camera_snapshot_b64()
        except Exception as exc:
            log.warning("camera snapshot failed: %s", exc)
            return None
        jpeg = base64.b64decode(b64)
        with self._cam_lock:
            self._cam_jpeg = jpeg
            self._cam_ts = time.time()
        return jpeg

    def emit(self, kind: str, payload: dict[str, Any] | None = None) -> None:
        """Thread-safe event emit to all WebSocket clients."""
        msg = {"kind": kind, "payload": payload or {}, "ts": time.time()}
        if self._loop is None:
            self._event_q.put(msg)
            return
        asyncio.run_coroutine_threadsafe(self._broadcast(msg), self._loop)

    # --- internal ---

    def _on_memory_changed(self) -> None:
        self.emit("memory_changed",
                  {"memories": [m.to_dict() for m in self.memory.list()]})

    async def _telemetry_loop_async(self) -> None:
        """Polls sensors every 2 s and broadcasts to the WebSocket."""
        while True:
            try:
                t = await asyncio.to_thread(self.get_telemetry)
                await self._broadcast({"kind": "telemetry", "payload": t,
                                       "ts": time.time()})
            except Exception as exc:
                log.warning("telemetry loop error: %s", exc)
            await asyncio.sleep(2.0)

    async def _broadcast(self, msg: dict[str, Any]) -> None:
        text = json.dumps(msg, default=str)
        with self._connections_lock:
            conns = list(self._connections)
        dead: list[WebSocket] = []
        for ws in conns:
            try:
                await ws.send_text(text)
            except Exception:
                dead.append(ws)
        if dead:
            with self._connections_lock:
                for ws in dead:
                    if ws in self._connections:
                        self._connections.remove(ws)

    def _drain_pending(self) -> None:
        """Deliver events queued before server start once the loop is bound."""
        while True:
            try:
                msg = self._event_q.get_nowait()
            except queue_mod.Empty:
                return
            asyncio.run_coroutine_threadsafe(self._broadcast(msg), self._loop)

    def _setup_routes(self) -> None:
        app = self.app

        @app.on_event("startup")
        async def _startup() -> None:
            self._loop = asyncio.get_running_loop()
            self._drain_pending()
            asyncio.create_task(self._telemetry_loop_async())

        @app.get("/api/camera.jpg")
        async def api_camera() -> Response:
            jpeg = await asyncio.to_thread(self.get_camera_jpeg)
            if jpeg is None:
                return Response(status_code=503, content=b"camera unavailable")
            return Response(content=jpeg, media_type="image/jpeg",
                            headers={"Cache-Control": "no-store"})

        @app.get("/api/telemetry")
        async def api_telemetry() -> JSONResponse:
            t = await asyncio.to_thread(self.get_telemetry)
            return JSONResponse(t)

        @app.get("/api/i18n")
        async def api_i18n() -> JSONResponse:
            return JSONResponse({"lang": i18n.lang(),
                                 "strings": i18n.strings_for_ui()})

        @app.get("/", response_class=HTMLResponse)
        async def index() -> HTMLResponse:
            return HTMLResponse(_INDEX_HTML.read_text())

        @app.get("/api/tools")
        async def api_tools() -> JSONResponse:
            grouped: dict[str, list[dict[str, Any]]] = {}
            for spec in skills.all_tools().values():
                grouped.setdefault(spec.category, []).append({
                    "name": spec.name,
                    "description": spec.description,
                    "params": [
                        {"name": p.name,
                         "type": p.type.__name__,
                         "default": p.default if not p.required else None,
                         "required": p.required,
                         "choices": list(p.choices) if p.choices else None}
                        for p in spec.params
                    ],
                })
            return JSONResponse(grouped)

        @app.get("/api/state")
        async def api_state() -> JSONResponse:
            key_present = bool(os.environ.get("OPENAI_API_KEY"))
            return JSONResponse({
                "key_status": "ok" if key_present else "missing",
                "key_source": "env",
                "memories": [m.to_dict() for m in self.memory.list()],
                "led_state": self.leds.current_lifecycle,
                "led_mood": self.leds.current_mood,
            })

        @app.websocket("/ws")
        async def ws_endpoint(ws: WebSocket) -> None:
            await ws.accept()
            with self._connections_lock:
                self._connections.append(ws)
            await ws.send_text(json.dumps({
                "kind": "hello",
                "payload": {
                    "tool_count": len(skills.all_tools()),
                    "memories": [m.to_dict() for m in self.memory.list()],
                    "key_status": "ok" if os.environ.get("OPENAI_API_KEY") else "missing",
                    "paused": self.paused.is_set(),
                },
            }))
            try:
                while True:
                    text = await ws.receive_text()
                    try:
                        msg = json.loads(text)
                    except json.JSONDecodeError:
                        continue
                    await self._handle_client_msg(msg, ws)
            except WebSocketDisconnect:
                pass
            finally:
                with self._connections_lock:
                    if ws in self._connections:
                        self._connections.remove(ws)

    async def _handle_client_msg(self, msg: dict[str, Any], ws: WebSocket) -> None:
        t = msg.get("type")
        if t == "user_message":
            text = (msg.get("text") or "").strip()
            if text:
                # Synthetic bus event — the listen loop will pick this up
                # and send it through Agent.chat.
                self.bus.emit_force(SensorEvent(
                    kind="web_user_message",
                    payload={"text": text},
                ))
        elif t == "tool_call":
            name = msg.get("name")
            args = msg.get("args") or {}
            await self._run_direct_tool(name, args)
        elif t == "stop" or t == "stop_soft" or t == "stop_hard":
            # Unified: one stop = body_stop + LLM abort + neutral pose
            self.stop_soft.set()
            self.stop_hard.set()
            try:
                from .. import hardware
                hardware.dog().body_stop()
                hardware.dog().head_move([[0, 0, 0]], immediately=True, speed=80)
                hardware.flow().run("stand")
            except Exception as exc:
                log.warning("stop neutral pose failed: %s", exc)
            try:
                self.leds.set_lifecycle("idle")
            except Exception:
                pass
            self.emit("stop_requested", {})
        elif t == "pause":
            self.paused.set()
            try:
                self.leds.set_lifecycle("paused")
            except Exception:
                pass
            self.emit("paused", {"value": True})
        elif t == "resume":
            self.paused.clear()
            try:
                self.leds.set_lifecycle("idle")
            except Exception:
                pass
            self.emit("paused", {"value": False})
        elif t == "memory_add":
            try:
                self.memory.add(msg.get("text", ""))
            except Exception as exc:
                self.emit("error", {"context": "memory_add", "error": str(exc)})
        elif t == "memory_edit":
            try:
                self.memory.edit(msg.get("id"), msg.get("text", ""))
            except Exception as exc:
                self.emit("error", {"context": "memory_edit", "error": str(exc)})
        elif t == "memory_delete":
            self.memory.delete(msg.get("id"))
        elif t == "set_openai_key":
            await self._set_openai_key(msg.get("key", ""), bool(msg.get("persist")))

    async def _run_direct_tool(self, name: str, args: dict[str, Any]) -> None:
        self.emit("tool_call_start", {"name": name, "args": args, "source": "web"})
        try:
            spec = skills.get(name)
            kwargs = skills.coerce_kwargs(spec, {k: str(v) for k, v in args.items()})
            result = await asyncio.to_thread(spec.call, **kwargs)
            self.emit("tool_call_end", {"name": name, "result": result, "ok": True})
        except Exception as exc:
            log.exception("direct tool failed")
            self.emit("tool_call_end", {"name": name, "error": str(exc), "ok": False})

    async def _set_openai_key(self, key: str, persist: bool) -> None:
        key = key.strip()
        if not key.startswith("sk-"):
            self.emit("key_status", {"status": "invalid",
                                     "reason": "key must start with sk-"})
            return
        # Validation: mini test call.
        try:
            from openai import OpenAI
            await asyncio.to_thread(lambda: OpenAI(api_key=key).models.list())
        except Exception as exc:
            self.emit("key_status", {"status": "invalid", "reason": str(exc)})
            return
        os.environ["OPENAI_API_KEY"] = key
        if persist:
            try:
                self._persist_key(key)
            except Exception as exc:
                self.emit("key_status", {"status": "ok",
                                         "warning": f"saved in-memory only: {exc}"})
                return
        self.emit("key_status", {"status": "ok",
                                 "source": "secrets.env" if persist else "memory"})

    def _persist_key(self, key: str) -> None:
        # Project root = three levels up from this file (aidog/web/server.py).
        secrets_path = Path(__file__).resolve().parents[2] / "secrets.env"
        lines: list[str] = []
        if secrets_path.exists():
            for line in secrets_path.read_text().splitlines():
                if not line.strip().startswith("OPENAI_API_KEY="):
                    lines.append(line)
        lines.append(f"OPENAI_API_KEY={key}")
        fd, tmp_path = tempfile.mkstemp(prefix="secrets-", dir=str(secrets_path.parent))
        with os.fdopen(fd, "w") as f:
            f.write("\n".join(lines) + "\n")
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, secrets_path)
