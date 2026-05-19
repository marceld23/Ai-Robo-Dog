"""
Wake-word detection with Vosk (local, German).

Streams audio from arecord into a Vosk KaldiRecognizer with a fixed grammar
on the wake phrase(s) — very low CPU compared to unconstrained ASR.
As soon as the phrase is detected, `wait_for_wake()` returns.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path

from vosk import KaldiRecognizer, Model, SetLogLevel

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
CHUNK_BYTES = 4000


class WakeWord:
    def __init__(self, *, model_path: str | os.PathLike, phrases: list[str]):
        path = Path(os.path.expanduser(str(model_path)))
        if not path.is_absolute():
            project_root = Path(__file__).resolve().parents[2]
            path = (project_root / path).resolve()
        if not path.is_dir():
            raise FileNotFoundError(f"Vosk model not found: {path}")
        SetLogLevel(-1)
        log.info("loading vosk model from %s", path)
        self.model = Model(str(path))
        # "[unk]" as a catch-all for anything that is none of the phrases —
        # prevents the recognizer from returning arbitrary text.
        self.grammar = json.dumps([*phrases, "[unk]"])
        self.phrases = [p.lower() for p in phrases]

    def _new_recognizer(self) -> KaldiRecognizer:
        rec = KaldiRecognizer(self.model, SAMPLE_RATE, self.grammar)
        return rec

    def wait_for_wake(self, *, device: str | None = None) -> str:
        """Blocks until a wake phrase is detected, then returns it."""
        rec = self._new_recognizer()
        cmd = ["arecord", "-q", "-f", "S16_LE", "-r", str(SAMPLE_RATE),
               "-c", "1", "-t", "raw"]
        if device:
            cmd[1:1] = ["-D", device]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        assert proc.stdout is not None
        try:
            while True:
                chunk = proc.stdout.read(CHUNK_BYTES)
                if not chunk:
                    raise RuntimeError("arecord ended unexpectedly")
                if rec.AcceptWaveform(chunk):
                    text = json.loads(rec.Result()).get("text", "").strip().lower()
                    if text and text != "[unk]":
                        log.info("wake matched: %r", text)
                        for phrase in self.phrases:
                            if phrase in text:
                                return phrase
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                proc.kill()
