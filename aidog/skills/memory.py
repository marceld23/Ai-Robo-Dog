"""Memory tools — Buddy learns tricks permanently."""
from __future__ import annotations

from typing import Any

from ..memory import MemoryStore
from .registry import tool


@tool("remember",
      "Speichere eine Verhaltensweise oder einen Trick dauerhaft. Nutze das, "
      "wenn der Mensch dir was beibringen will (z.B. 'wenn ich Pfötchen sage, "
      "gib die rechte Pfote'). Fasse die Anweisung in einem prägnanten Satz "
      "zusammen — diese Erinnerung wird in jedem zukünftigen Turn als Kontext "
      "an dich zurückgegeben, also formuliere sie so dass du sie auch in 3 "
      "Tagen noch verstehst.",
      category="memory")
def remember(text: str) -> dict[str, Any]:
    mem = MemoryStore.instance().add(text)
    return {"id": mem.id, "text": mem.text}


@tool("forget",
      "Lösche eine gespeicherte Erinnerung anhand ihrer ID. Nutze das, wenn "
      "der Mensch dir explizit sagt 'vergiss das' oder 'nicht mehr machen'.",
      category="memory")
def forget(memory_id: str) -> dict[str, Any]:
    ok = MemoryStore.instance().delete(memory_id)
    return {"deleted": ok, "id": memory_id}
