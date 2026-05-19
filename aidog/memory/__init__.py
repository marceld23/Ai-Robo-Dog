"""Persistente Erinnerungen für Buddy. JSON-File mit Lock + atomic write."""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_DEFAULT_PATH = Path(__file__).resolve().parents[1] / "data" / "memories.json"
_MAX_TEXT_LEN = 200
_MAX_ENTRIES = 50


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Memory:
    id: str
    text: str
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MemoryStore:
    _instance: "MemoryStore | None" = None
    _singleton_lock = threading.Lock()

    def __init__(self, path: Path = _DEFAULT_PATH) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._listeners: list[Any] = []
        if not self.path.exists():
            self._write_atomic([])

    @classmethod
    def instance(cls) -> "MemoryStore":
        with cls._singleton_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def _read(self) -> list[dict[str, Any]]:
        try:
            return json.loads(self.path.read_text() or "[]")
        except json.JSONDecodeError as exc:
            log.error("memories.json corrupt (%s) — starting fresh", exc)
            return []

    def _write_atomic(self, items: list[dict[str, Any]]) -> None:
        fd, tmp_path = tempfile.mkstemp(prefix="memories-", suffix=".json",
                                        dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(items, f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, self.path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def list(self) -> list[Memory]:
        with self._lock:
            return [Memory(**m) for m in self._read()]

    def add(self, text: str) -> Memory:
        text = text.strip()
        if not text:
            raise ValueError("memory text empty")
        if len(text) > _MAX_TEXT_LEN:
            text = text[:_MAX_TEXT_LEN]
        with self._lock:
            items = self._read()
            if len(items) >= _MAX_ENTRIES:
                # Älteste verdrängen, wenn voll. Verhindert unbounded Growth.
                items.sort(key=lambda m: m.get("updated_at", ""))
                items.pop(0)
            mem = Memory(id=uuid.uuid4().hex[:8], text=text,
                         created_at=_now(), updated_at=_now())
            items.append(mem.to_dict())
            self._write_atomic(items)
        log.info("memory added: %s", mem.text)
        self._notify()
        return mem

    def edit(self, mem_id: str, text: str) -> Memory:
        text = text.strip()
        if not text:
            raise ValueError("memory text empty")
        if len(text) > _MAX_TEXT_LEN:
            text = text[:_MAX_TEXT_LEN]
        with self._lock:
            items = self._read()
            for m in items:
                if m["id"] == mem_id:
                    m["text"] = text
                    m["updated_at"] = _now()
                    self._write_atomic(items)
                    log.info("memory edited: %s → %s", mem_id, text)
                    self._notify()
                    return Memory(**m)
        raise KeyError(f"memory {mem_id!r} not found")

    def delete(self, mem_id: str) -> bool:
        with self._lock:
            items = self._read()
            new = [m for m in items if m["id"] != mem_id]
            if len(new) == len(items):
                return False
            self._write_atomic(new)
        log.info("memory deleted: %s", mem_id)
        self._notify()
        return True

    def render_for_prompt(self) -> str | None:
        items = self.list()
        if not items:
            return None
        lines = [f"- {m.text}" for m in items]
        return ("Du erinnerst dich an folgende vom Menschen beigebrachte "
                "Verhaltensweisen (höhere Priorität als allgemeine "
                "Hund-Reaktion, niemals deine Persona-Regel \"keine "
                "Wortantworten\" überschreiben):\n" + "\n".join(lines))

    # Listener-API für Web-UI Broadcast (Phase 10).
    def add_listener(self, callback: Any) -> None:
        with self._lock:
            self._listeners.append(callback)

    def remove_listener(self, callback: Any) -> None:
        with self._lock:
            try:
                self._listeners.remove(callback)
            except ValueError:
                pass

    def _notify(self) -> None:
        for cb in list(self._listeners):
            try:
                cb()
            except Exception as exc:
                log.warning("memory listener failed: %s", exc)
