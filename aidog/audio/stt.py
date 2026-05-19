"""OpenAI Whisper API transcription."""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass

from openai import OpenAI

log = logging.getLogger(__name__)

# On silence / background noise Whisper tends to hallucinate standard phrases
# from its training data (YouTube subtitles etc.). We filter the most common
# ones out and discard the turn.
_HALLUCINATIONS = {
    "untertitel der amara.org-community",
    "untertitelung des zdf für funk, 2017",
    "untertitelung im auftrag des zdf, 2017",
    "untertitel im auftrag des zdf, 2021",
    "thanks for watching",
    "thank you for watching",
    "vielen dank für's zuschauen",
    "vielen dank fürs zuschauen",
    "tschüss",
    ".",
    "you",
}


@dataclass
class STTResult:
    text: str
    duration_sec: float


def is_likely_hallucination(text: str) -> bool:
    if not text:
        return True
    norm = text.strip().lower().rstrip(".!?")
    return norm in _HALLUCINATIONS


class WhisperSTT:
    def __init__(self, *, model: str = "whisper-1", language: str = "de",
                 client: OpenAI | None = None):
        self.model = model
        self.language = language
        self.client = client or OpenAI()

    def transcribe(self, wav_bytes: bytes) -> STTResult:
        import time
        started = time.monotonic()
        buf = io.BytesIO(wav_bytes)
        buf.name = "audio.wav"
        resp = self.client.audio.transcriptions.create(
            model=self.model,
            file=buf,
            language=self.language,
        )
        duration = time.monotonic() - started
        text = resp.text.strip()
        log.info("whisper %.2fs: %r", duration, text)
        return STTResult(text=text, duration_sec=duration)
