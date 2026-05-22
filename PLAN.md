# PiDog v2 LLM Agent — Remaining Work

> The system architecture and how the built components work are documented in
> [ARCHITECTURE.md](ARCHITECTURE.md). This file tracks only what is **not yet
> done** plus the open risks worth keeping in view.

**Project name:** `aidog` · **Project directory:** `/home/dog/Ai-Robo-Dog/` ·
**Package manager:** `uv`

## Status

The built system (skeleton, 45 skills, OpenAI function calling, Whisper STT,
Vosk wake word, on-demand + push sensors with touch / ultrasonic /
sound-direction / battery, LED lifecycle, critical battery shutdown, Web UI,
memory, WiFi onboarding) is documented in [ARCHITECTURE.md](ARCHITECTURE.md).
What remains open:

| Phase | Status |
|---|---|
| 1 Personality tuning | ⏳ open |
| 2 Robustness | ⏳ open |
| 3 IMU tilt/fall sensor (`aidog/sensors/imu.py`) | ⏳ open |

---

## Phase 1 — Personality tuning

Subjective quality work on the dog persona, ongoing.

- Iterate on `aidog/llm/prompt.py` (DE + EN) so reactions feel more dog-like:
  better emotion→tool-combo mappings, less repetition, livelier idle behavior.
- Tune `set_mood` color/bps mappings against how they actually read on the
  chest strip.
- **Success test:** subjective quality check across a range of voice commands
  and sensor events.

## Phase 2 — Robustness

- **Reconnect / token refresh:** survive Wi-Fi drops and transient OpenAI
  errors mid-turn (Whisper + chat). Filler pattern (pant + yellow LED pulse)
  while waiting; clean recovery instead of a crashed loop.
- **Watchdog:** detect a hung listen loop / stuck arecord / frozen camera and
  restart the affected piece without taking the whole process down.
- **Success test:** 30 min of continuous operation under mixed
  voice/sensor/Web-UI load with no crash and no GPIO-busy lockup.

## Phase 3 — IMU tilt/fall sensor (`aidog/sensors/imu.py`)

Planned but not yet implemented (touch + ultrasonic + sound direction shipped
first).

- `dog.pitch` / `dog.roll` from the IMU thread.
- "abnormal": `|pitch| > 30°` or `|roll| > 30°` held > 0.5 s → `tilt_abnormal`.
- Fall: `|az| < 4000` (free fall) → `fall`, severity `critical`.
- Emit only when `action_flow.posture != LIE` (lying down is intentional, not a
  fall). Thresholds already present in `config.yaml sensors.imu`.

---

## Open risks & points

1. **PyAudio + PulseAudio conflicts** — avoided so far by recording via an
   `arecord` subprocess rather than PyAudio; keep this in mind if recording is
   reworked.
2. **Whisper API latency** on poor Wi-Fi (5+ s noticeable) — covered by the
   filler pattern; revisit under phase 2 (robustness).
3. **Sound direction & self-noise** — the dog hears itself; sound events are
   processed only when `action_flow.is_idle()`. Verify this holds under load.
4. **Tool-call loops** — bounded by `max_tool_iterations=8`.
5. **Image token cost** — vision uses `detail="low"` (~85 tokens); the camera
   tool fires only when needed.
6. **Wake-word false positives** — Vosk small can be finicky. Plan B: Picovoice
   Porcupine free tier.
7. **LLM tries to speak anyway** — `tool_choice="required"` + prompt hardness;
   `content` is logged only, never acted on.
8. **Battery voltage spikes** from servo load — smoothed by the running average
   + downward hysteresis; the critical live test is still pending (battery has
   been in the normal zone).
9. **Preset sounds via `dog.speak()`** — `vocal.py` bypasses `speak_block` with
   `paplay`, but `flow().run("howling"|"pant"|"lie"+snoring)` still calls
   Pidog's presets which use `dog.speak()` internally. If those hang under the
   phase-2 stress test, switch the presets to `_play` as well.
10. **WiFi onboarding live test** — scan/connectivity/routes/CLI verified
    non-disruptively; the AP raise drops the Pi's own WiFi/SSH, so the full
    AP + captive-portal test must be done locally on the device.
11. **nmcli privileges** — `general` / `wifi list` work unprivileged here, but
    `hotspot` / `connect` run as root via the systemd unit. Revisit if a tight
    polkit rule is preferred over root.
12. **Captive-portal detection** differs per OS and version — needs testing on
    current iOS/Android; manual fallback URL `http://192.168.4.1` documented.

---

## Sources

- [SunFounder PiDog Docs](https://docs.sunfounder.com/projects/pidog/en/latest/) ·
  [PiDog GitHub](https://github.com/sunfounder/pidog)
- [Vosk Speech Recognition](https://alphacephei.com/vosk/)
- [openWakeWord](https://github.com/dscripka/openWakeWord) /
  [Picovoice Porcupine](https://picovoice.ai/platform/porcupine/) (wake-word backup)
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (local STT backup)
- [OpenAI Function Calling](https://platform.openai.com/docs/guides/function-calling) ·
  [Whisper API](https://platform.openai.com/docs/api-reference/audio)
- [WebRTC VAD](https://github.com/wiseman/py-webrtcvad)
</content>
