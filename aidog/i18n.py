"""
Tiny config-driven i18n. Language is fixed at start via config.yaml
`language: de|en`. `t(key)` returns the string for the active language,
falling back to English then to the key itself.

The Web UI gets the whole table for its language via /api/i18n; runtime
strings (CLI / server emits) call `t()` directly.
"""
from __future__ import annotations

from . import config as _cfg

_DEFAULT = "en"
_cached_lang: str | None = None


def lang() -> str:
    global _cached_lang
    if _cached_lang is None:
        _cached_lang = str(_cfg.load().get("language", "de")).lower()
        if _cached_lang not in _STRINGS:
            _cached_lang = _DEFAULT
    return _cached_lang


def t(key: str, **kw: object) -> str:
    table = _STRINGS.get(lang(), _STRINGS[_DEFAULT])
    s = table.get(key) or _STRINGS[_DEFAULT].get(key) or key
    return s.format(**kw) if kw else s


def strings_for_ui() -> dict[str, str]:
    """Full string table for the active language, for the Web UI."""
    merged = dict(_STRINGS[_DEFAULT])
    merged.update(_STRINGS.get(lang(), {}))
    return {k: v for k, v in merged.items() if k.startswith("ui.")}


_STRINGS: dict[str, dict[str, str]] = {
    "de": {
        # --- Web UI ---
        "ui.title": "Buddy",
        "ui.connecting": "verbinde…",
        "ui.connected": "verbunden",
        "ui.disconnected": "getrennt",
        "ui.key_unknown": "key?",
        "ui.key_ok": "key ✓",
        "ui.key_missing": "key fehlt",
        "ui.intervene": "Eingriff",
        "ui.stop": "⏹ STOP",
        "ui.pause": "⏸ Pause",
        "ui.resume": "▶ Weiter",
        "ui.pause_hint": "Pause: Sensoren laufen weiter, aber kein LLM-Call.",
        "ui.camera": "Sicht",
        "ui.sensors": "Sensoren",
        "ui.dist_front": "Distanz vorne",
        "ui.battery": "Akku",
        "ui.pitch_roll": "Pitch / Roll",
        "ui.led": "LED",
        "ui.last_sound": "Letztes Geräusch (Richtung)",
        "ui.compass_n": "N (vorn)",
        "ui.live_log": "Live-Log",
        "ui.instruction": "Anweisung an Buddy",
        "ui.input_placeholder": "z.B. setz dich hin",
        "ui.send": "Senden",
        "ui.memories": "Erinnerungen",
        "ui.mem_empty": "Noch keine Erinnerungen — Buddy lernt von Sprache "
                        "oder du fügst sie unten hinzu.",
        "ui.mem_placeholder": "Neue Erinnerung…",
        "ui.mem_edit": "bearbeiten",
        "ui.mem_delete": "löschen",
        "ui.mem_edit_prompt": "Erinnerung bearbeiten:",
        "ui.mem_delete_confirm": "Erinnerung löschen?",
        "ui.tools_debug": "Direkte Tool-Calls (Debug)",
        "ui.settings_key": "OpenAI API Key",
        "ui.settings_hint": "Wird per Test-Call validiert.",
        "ui.settings_persist": "In secrets.env speichern",
        "ui.cancel": "Abbrechen",
        "ui.save": "Speichern",
        "ui.camera_unavailable": "Kamera nicht verfügbar",
        "ui.sound_now": "gerade jetzt",
        "ui.sound_ago_s": "vor {s} s",
        "ui.sound_ago_min": "vor {m} min",
        # --- runtime / CLI ---
        "rt.ready": "Buddy bereit. {n} Tools geladen.",
        "rt.listening": "Buddy wartet auf Sprache + Sensor-Events. Strg+C zum Beenden.",
        "rt.web_running": "Web-UI läuft auf {url}",
        "rt.no_voice": "(keine Sprache erkannt, {sec:.1f}s)",
        "rt.hallucination": "(verwerfe Halluzination)",
    },
    "en": {
        # --- Web UI ---
        "ui.title": "Buddy",
        "ui.connecting": "connecting…",
        "ui.connected": "connected",
        "ui.disconnected": "disconnected",
        "ui.key_unknown": "key?",
        "ui.key_ok": "key ✓",
        "ui.key_missing": "key missing",
        "ui.intervene": "Intervene",
        "ui.stop": "⏹ STOP",
        "ui.pause": "⏸ Pause",
        "ui.resume": "▶ Resume",
        "ui.pause_hint": "Pause: sensors keep running, but no LLM call.",
        "ui.camera": "Vision",
        "ui.sensors": "Sensors",
        "ui.dist_front": "Distance ahead",
        "ui.battery": "Battery",
        "ui.pitch_roll": "Pitch / Roll",
        "ui.led": "LED",
        "ui.last_sound": "Last sound (direction)",
        "ui.compass_n": "N (front)",
        "ui.live_log": "Live log",
        "ui.instruction": "Instruction to Buddy",
        "ui.input_placeholder": "e.g. sit down",
        "ui.send": "Send",
        "ui.memories": "Memories",
        "ui.mem_empty": "No memories yet — Buddy learns from speech "
                        "or you add them below.",
        "ui.mem_placeholder": "New memory…",
        "ui.mem_edit": "edit",
        "ui.mem_delete": "delete",
        "ui.mem_edit_prompt": "Edit memory:",
        "ui.mem_delete_confirm": "Delete memory?",
        "ui.tools_debug": "Direct tool calls (debug)",
        "ui.settings_key": "OpenAI API key",
        "ui.settings_hint": "Validated with a test call.",
        "ui.settings_persist": "Save to secrets.env",
        "ui.cancel": "Cancel",
        "ui.save": "Save",
        "ui.camera_unavailable": "camera unavailable",
        "ui.sound_now": "just now",
        "ui.sound_ago_s": "{s} s ago",
        "ui.sound_ago_min": "{m} min ago",
        # --- runtime / CLI ---
        "rt.ready": "Buddy ready. {n} tools loaded.",
        "rt.listening": "Buddy is waiting for speech + sensor events. Ctrl+C to quit.",
        "rt.web_running": "Web UI running at {url}",
        "rt.no_voice": "(no speech detected, {sec:.1f}s)",
        "rt.hallucination": "(discarding hallucination)",
    },
}
