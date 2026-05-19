"""
Push-to-talk recorder: arecord subprocess + webrtcvad endpointing.

Reads 16-kHz/16-bit/mono raw from the voicehat via arecord, checks every 20-ms
frame with webrtcvad and stops recording after `silence_end_sec` of silence or
`max_record_sec` total time. Returns the recording as WAV bytes (BytesIO),
directly usable with the Whisper API.
"""
from __future__ import annotations

import io
import logging
import subprocess
import time
import wave
from dataclasses import dataclass
from typing import Optional

import webrtcvad

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
SAMPLE_WIDTH = 2
CHANNELS = 1
FRAME_MS = 20
FRAME_BYTES = int(SAMPLE_RATE * FRAME_MS / 1000) * SAMPLE_WIDTH


@dataclass
class Recording:
    wav: bytes
    duration_sec: float
    voiced_frames: int
    total_frames: int

    @property
    def has_voice(self) -> bool:
        # 15 frames @ 20ms = 300ms of actually spoken audio. Below that Whisper
        # mostly hallucinates training-data phrases, while at the same time the
        # voicehat mic often only delivers 300-500ms of usable frames for short
        # commands like "bell mal".
        return self.voiced_frames >= 15


def record_until_silence(
    *,
    max_record_sec: float = 8.0,
    silence_end_sec: float = 1.5,
    min_voice_sec: float = 0.3,
    vad_aggressiveness: int = 2,
    device: Optional[str] = None,
) -> Recording:
    vad = webrtcvad.Vad(vad_aggressiveness)
    silence_frames_needed = int(silence_end_sec * 1000 / FRAME_MS)
    min_voice_frames = int(min_voice_sec * 1000 / FRAME_MS)
    max_frames = int(max_record_sec * 1000 / FRAME_MS)

    cmd = ["arecord", "-q", "-f", "S16_LE", "-r", str(SAMPLE_RATE),
           "-c", str(CHANNELS), "-t", "raw"]
    if device:
        cmd[1:1] = ["-D", device]

    log.debug("starting arecord: %s", " ".join(cmd))
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.stdout is not None

    frames: list[bytes] = []
    voiced_total = 0
    silence_run = 0
    started = time.monotonic()
    try:
        for _ in range(max_frames):
            chunk = proc.stdout.read(FRAME_BYTES)
            if len(chunk) < FRAME_BYTES:
                break
            frames.append(chunk)
            if vad.is_speech(chunk, SAMPLE_RATE):
                voiced_total += 1
                silence_run = 0
            elif voiced_total >= min_voice_frames:
                # Only after real speech activity (not for single cough
                # frames) does silence end the recording.
                silence_run += 1
                if silence_run >= silence_frames_needed:
                    break
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            proc.kill()

    duration = time.monotonic() - started
    raw = b"".join(frames)

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(CHANNELS)
        w.setsampwidth(SAMPLE_WIDTH)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(raw)
    buf.seek(0)

    log.info("recorded %.2fs, %d/%d voiced frames", duration, voiced_total, len(frames))
    return Recording(wav=buf.getvalue(), duration_sec=duration,
                     voiced_frames=voiced_total, total_frames=len(frames))
