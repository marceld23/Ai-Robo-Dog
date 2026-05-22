# Ai-Robo-Dog — Architecture

> How the `aidog` system is built and how it works at runtime. The PiDog v2 on a
> Raspberry Pi 4 behaves like a dog, driven by an LLM via tool calling. It never
> speaks words — it communicates only through dog sounds, movement, and the
> chest LED strip.
>
> Open planning and remaining work live in [PLAN.md](PLAN.md). User-facing setup
> and usage are in [README.md](README.md). Conventions for contributors are in
> [AGENTS.md](AGENTS.md).

**Project name:** `aidog` · **Project directory:** `/home/dog/Ai-Robo-Dog/` ·
**Package manager:** `uv` · **Python:** 3.13

---

## 1 · Hardware

PiDog v2 on a Raspberry Pi 4:

- 12 metal servos (8 legs, 3 head yaw/roll/pitch, 1 tail)
- 5 MP camera in the snout
- HC-SR04 ultrasonic sensor (forehead)
- 6-DoF IMU (SH3001, accel + gyro)
- TR16F064B sound-direction sensor (360° in 20° steps)
- 2× touch sensors on the head (front + rear, slide detection)
- 11-LED RGB strip on the chest
- Speaker (voicehat I2S HAT) + microphone
- 2× 18650 batteries (7.4 V nominal, ~8.4 V full, ~6.0 V empty)

### Vendor libraries (not in this repo)

The SunFounder libraries `pidog`, `vilib`, `robot_hat` (GPLv3) are installed
**system-wide** under `/usr/local/lib/python3.13/dist-packages/` by SunFounder's
installer. Our venv inherits them via `--system-site-packages` and imports them
normally. Reference source clones live in `~/pidog`, `~/vilib`, `~/robot-hat`
and must never be edited (see [AGENTS.md](AGENTS.md)).

Key vendor classes we build on directly:

- `pidog.Pidog()` — main class, owns threads for legs/head/tail/IMU/ultrasonic/RGB
- `pidog.action_flow.ActionFlow` — `OPERATIONS` map of ~24 named actions
- `pidog.preset_actions` — complex sequences (scratch, handshake, howling, …)

---

## 2 · Stack decisions

| Component | Choice |
|---|---|
| LLM | OpenAI GPT (`gpt-5.4-mini`, multimodal — vision + function calling) |
| STT | OpenAI Whisper API (`whisper-1`, cloud, good German recognition) |
| Wake word | Vosk keyword spotting (local, German/English small models) |
| TTS | **NONE** — the dog does not speak |
| Language (understanding) | German + English (`config.yaml language:`) |
| Language (response) | only dog sounds + movement + LED |

**Persona constraint:** the assistant message `content` is ignored. The LLM
"speaks" exclusively by selecting tools. `tool_choice="required"` on the first
iteration forces at least one tool call.

---

## 3 · Runtime architecture

```
                ┌────────────────────────────────────────────────────┐
                │                  PiDogAgent  (orchestrator)         │
                └────────────────────────────────────────────────────┘
                          ▲                              │
       Wake / Audio       │                              │ Tool calls
                          │                              ▼
   ┌─────────────┐  ┌──────────────┐               ┌─────────────────┐
   │ WakeWord    │─▶│ AudioCapture │─▶ Whisper API │  Tool Dispatcher│
   │ (Vosk)      │  │ + webrtcvad  │   (STT)       │                 │
   └─────────────┘  └──────────────┘     │         └────┬───────┬────┘
                                         ▼              │       │
                          ┌─────────────────────────────┘       │
                          ▼                                      ▼
                 ┌──────────────────┐                  ┌──────────────────┐
                 │   LLMClient      │                  │   Robot Skills   │
                 │ (OpenAI GPT)     │                  │  (Sound/Motion/  │
                 │ tool_choice=req  │                  │   LED/Mood/Mem)  │
                 └──────────────────┘                  └──────────────────┘
                          ▲                                      │
                          │ Events (push)                        │
                 ┌────────┴──────────────┐                       │
                 │  Sensor Event Bus     │                       │
                 │  (threading.Queue)    │                       │
                 └───────────────────────┘                       │
                          ▲                                      │
        ┌──────┬──────┬───┴────┬──────────┬──────────┬──────┐    │
   ┌────────┐ ┌──────────┐ ┌──────┐  ┌────────┐ ┌────────┐ ┌──────────┐
   │Ultra-  │ │Sound-Dir │ │ IMU  │  │Touch   │ │Battery │ │  Camera  │◀┘
   │sonic   │ │          │ │(plan)│  │        │ │Monitor │ │ (vilib)  │
   └────────┘ └──────────┘ └──────┘  └────────┘ └────────┘ └──────────┘

                          ┌──────────────────┐
                          │  LedController   │ ◀── auto lifecycle + LLM (set_mood)
                          └──────────────────┘
```

The sensor bus is **threading-based** (`threading.Queue` + `threading.Event`),
not asyncio — chosen as the pragmatic fit for the synchronous Pidog API. The
Web UI process runs the listen loop in a daemon thread and bridges events to the
browser over a WebSocket.

---

## 4 · Project layout

```
/home/dog/Ai-Robo-Dog/          # project root
├── pyproject.toml              # PEP 621 + [tool.uv] (python-preference=only-system)
├── .python-version             # 3.13
├── uv.lock                     # committed
├── secrets.env                 # OPENAI_API_KEY (chmod 600, gitignored)
├── secrets.env.example
├── config.yaml                 # all parameters (incl. not-yet-active phases)
├── start.sh                    # Web UI launcher (kills stale procs, sets audio env)
├── main.py                     # CLI: list / describe / call / sequence / chat / listen / web / netcfg
├── ARCHITECTURE.md             # ← this document
├── PLAN.md                     # remaining work + open risks
├── README.md                   # setup + usage
├── AGENTS.md                   # conventions for AI assistants
├── deploy/                     # systemd units (netcfg + web)
└── aidog/                      # Python package
    ├── config.py               # YAML + dotenv loader
    ├── log.py                  # stdlib logging
    ├── hardware.py             # Pidog() + ActionFlow() singleton, atexit close, audio routing, GPIO cleanup
    ├── i18n.py                 # DE/EN string tables (UI, prompt, np.* network-provisioning)
    ├── agent.py                # PiDogAgent orchestrator + tool dispatch
    ├── led/
    │   └── controller.py       # mood table + lifecycle override → rgb_strip.set_mode()
    ├── skills/
    │   ├── registry.py         # @tool decorator + registry (type hints → JSON schema)
    │   ├── locomotion.py       # walk_*/turn_*/trot/stop
    │   ├── postures.py         # sit/stand/lie_down/stretch/push_up/half_sit
    │   ├── vocal.py            # bark/howl/growl/whine/pant/snore/... (paplay bypass)
    │   ├── expressions.py      # wag_tail/nod/shake_head/tilt_head/look_around
    │   ├── tricks.py           # handshake/high_five/scratch/lick_hand/...
    │   ├── head.py             # set_head_pose
    │   ├── mood.py             # set_mood
    │   ├── perception.py       # read_distance/orientation/touch/battery/sound + get_camera_image
    │   └── memory.py           # remember / forget
    ├── llm/
    │   ├── client.py           # OpenAI client, tool loop, image sentinel, memory inject
    │   ├── prompt.py           # German/English dog persona system prompt
    │   └── schema.py           # ToolSpec → OpenAI tool JSON
    ├── audio/
    │   ├── recorder.py         # arecord subprocess + webrtcvad endpointing
    │   ├── stt.py              # OpenAI Whisper API + hallucination filter
    │   └── wake.py             # Vosk wake word (fixed grammar)
    ├── sensors/
    │   ├── bus.py              # threading.Queue + SensorEvent + busy/idle gate
    │   ├── touch.py            # polling + debounce
    │   ├── ultrasonic.py       # polling + hysteresis
    │   ├── sound_direction.py  # 33 Hz polling thread, stores LATEST angle+ts
    │   ├── wake_thread.py      # WakeWord wrapper in a daemon thread
    │   ├── battery.py          # polling + running avg + zone hysteresis + critical shutdown
    │   └── imu.py              # (planned — see PLAN.md)
    ├── memory/
    │   └── __init__.py         # MemoryStore singleton, JSON, atomic write, add_listener
    ├── web/
    │   ├── server.py           # FastAPI app, routes, WS bridge, telemetry, stop/pause, key entry
    │   ├── runner.py           # listen loop in a daemon thread
    │   └── static/index.html   # vanilla-JS mobile-responsive single page
    ├── netcfg/                 # WiFi onboarding (standalone)
    │   ├── manager.py          # state machine: check → AP → portal → connect → verify
    │   ├── nm.py               # thin nmcli wrapper
    │   └── portal/
    │       ├── server.py       # captive-portal FastAPI app
    │       └── static/index.html
    ├── models/                 # vosk models (gitignored)
    ├── sounds/                 # SunFounder dog sounds (gitignored, copied at first run)
    └── data/                   # memories.json (gitignored)
```

---

## 5 · Components

### 5.1 Hardware singleton (`hardware.py`)

`dog()` returns a process-wide `Pidog()` + `ActionFlow()`, registered for an
`atexit` `close()` (which runs `stop_and_lie()` — the correct shutdown). Beyond
construction it does the platform plumbing that makes audio and GPIO reliable:

- **`_patch_sunfounder_sudo()`** — monkey-patches `robot_hat.filedb` and
  `robot_hat.utils.run_command` so internal `sudo …` calls (chmod/chown,
  `killall pulseaudio`, `amixer`) become no-ops. Under `uv run` as user `dog`
  these would otherwise fail with "a terminal is required".
- **`_prepare_audio_routing()`** — `pactl` sets the default sink to the voicehat
  (`alsa_output.platform-soc_sound.stereo-fallback`) at 100 %, and sets
  `SDL_AUDIODRIVER=pulse`. Also forces `pinctrl set 20 a0` because GPIO20
  (PCM_DIN) is sometimes left as a plain input by a previous run, killing the mic.
- **`_kill_stale_gpio_holders()`** — kills hung predecessor processes that still
  hold `/dev/gpiochip0` (a hung pygame mixer can become an unkillable zombie).
- **`camera_snapshot_b64()`** — lazy vilib init, resize to max 512 px, JPEG q=75,
  base64. Vision calls use `detail="low"` (≈85 tokens fixed). Has a one-shot
  auto-recovery (`camera_close` + `camera_start`) if `Vilib.img` is still None
  after 0.5 s (Pi-camera frontend timeout, typical with a wobbly ribbon cable).

### 5.2 Skills + tool registry (`skills/`)

The `@tool(name, description, category=...)` decorator in `registry.py` reads
type hints and `Literal[...]` args to derive the OpenAI function-calling JSON
schema. **45 tools** in 8 categories: locomotion (6), posture (6), vocal (10),
expression (5), trick (8), head (1), mood (1), perception (6), memory (2).

`vocal.py` bypasses `dog.speak_block` entirely — `pygame.mixer.Sound.play()`
reliably hangs inside the Pidog multithread context. Instead `_play(name)` runs
`paplay <path>` directly on the voicehat sink, with sound files copied into the
project's own `aidog/sounds/`.

### 5.3 LLM client (`llm/client.py`)

- Model `gpt-5.4-mini` (multimodal — same model for text and vision turns).
- `run_turn(user_text, image_b64=None)`: first iteration `tool_choice="required"`,
  then `"auto"`; loops until no more `tool_calls` or `max_tool_iterations` (8).
- History trimmed at the oldest user turn (default 20). An assistant message is
  appended **only** if it has content or tool_calls (an empty `{"role":
  "assistant"}` triggers an OpenAI 400 on the next call).
- **Image sentinel:** a tool result starting with `__IMAGE_B64__:` is split into
  a `tool` message plus a following `user` message with an `image_url` block
  (`detail="low"`).
- **Memory inject:** all stored memories are rendered into a second system
  message before every call (no `recall` tool needed). The Web UI additionally
  injects a live telemetry snapshot as a system message each turn.

### 5.4 LedController (`led/controller.py`)

Two independent inputs — a lifecycle override and the LLM-set mood — combined by
priority in `_apply_locked()`:

```
error > battery_low > lifecycle (wake/listening/thinking/sleeping/paused)
                    > mood (LLM via set_mood) > default-idle (breath/white/0.3)
```

| Lifecycle state | Spec | Meaning |
|---|---|---|
| `idle` | transparent → mood/default | waiting for a trigger |
| `wake` | boom/cyan/2.0 | "hey buddy" just detected |
| `listening` | listen/green/1.5 | speak now (green ≠ wake cyan) |
| `thinking` | listen/yellow/1.5 | Whisper/LLM running, don't speak |
| `paused` | breath/magenta/0.4 | Web UI pause |
| `error` | monochromatic/red/0 | handler crash, visible ~1.5 s |
| `battery_low` | breath/red/0.5 | set by the battery monitor |
| `sleeping` | monochromatic/black/0 | off |

LLM moods (`set_mood`): happy, playful, love, curious, alert, angry, scared,
sad, sleepy → each mapped to a (mode, color, bps) spec. The mood persists past
the `acting` phase until the next mood change or idle timeout.

### 5.5 Sensor event bus (`sensors/`)

`SensorEvent(kind, payload, ts, severity)` flows through a `SensorBus` singleton
(`queue.Queue` + a busy/idle `threading.Event`). `emit()` drops events while the
agent is busy; `emit_force()` is for critical events. Each sensor runs as a
daemon thread with its own debounce:

- **touch** — 50 ms polling, 1 s debounce, maps `dual_touch.read()` → `touch`
  event with `style` (N/L/R/LS/RS). `FRONT_TO_REAR` = positive petting,
  `REAR_TO_FRONT` = annoying.
- **ultrasonic** — 200 ms polling, hysteresis (enter < 10 cm, leave ≥ 15 cm) →
  `too_close` (severity `warn`). Returns `null` (not -1) on no echo so the LLM
  doesn't treat it as "obstacle 1 cm away".
- **sound_direction** — dedicated 33 Hz polling thread (the voicehat detect
  signal is active only for ms); stores last angle + timestamp in `LATEST`.
  Only processed when `action_flow.is_idle()` (otherwise the dog hears itself).
- **battery** — see below.
- **wake_thread** — wraps `WakeWord`; pauses while the bus is busy to avoid an
  arecord conflict with the recording arecord.
- **imu** — planned (tilt/fall detection); see [PLAN.md](PLAN.md).

### 5.6 Battery monitor (`sensors/battery.py`)

30 s polling, running average over 5 samples (smooths servo voltage spikes),
50 mV hysteresis on downward zone changes. Emits `battery_zone_change` only on a
real zone change:

| Voltage | Zone | Auto behavior |
|---|---|---|
| > 7.8 V | energetic | normal |
| 7.2–7.8 V | normal | normal |
| 6.8–7.2 V | tired | LED brightness 0.5 |
| 6.4–6.8 V | sleepy | brightness 0.5 + `battery_low` LED (red breath) |
| 6.0–6.4 V | exhausted | brightness 0.5 + `battery_low` LED |
| < 5.8 V | critical | deterministic shutdown in the thread |

Critical shutdown does **not** go through the LLM: `dog.do_action("lie")` →
LEDs off → `hardware.shutdown()` → `os._exit(0)`, guaranteeing a clean lie-down.
The LLM also receives zone changes as events and reacts dog-tired / dog-lively.
`read_battery()` returns `{voltage, zone, percent}` (0–100 % linear 6.0–8.4 V).

### 5.7 Camera (on-demand)

`get_camera_image` → vilib snapshot → resize → JPEG → base64 sentinel, packed as
a multimodal block into the next LLM call. The `listen` loop and Web UI also
attach a camera image automatically on every turn.

### 5.8 Web UI (`web/`)

FastAPI + Uvicorn on `:8080`, single process sharing the hardware singleton; the
listen loop runs in a daemon thread and bridges to the browser via
`asyncio.run_coroutine_threadsafe`. LAN-only, no auth.

- **Endpoints:** `/` (HTML), `/api/tools`, `/api/state`, `/api/telemetry`,
  `/api/camera.jpg` (cached 1.5 s), `/ws` (bidirectional).
- **Telemetry loop** pushes a sensor snapshot every 2 s and injects the current
  values into the LLM as a system message each turn (distance, tilt, battery
  zone, last sound) — Buddy has sensor context without extra `read_*` calls.
- **Stop** — single button: `body_stop` + head 0,0,0 + `flow.run("stand")` +
  LLM-loop abort + LED idle. **Voice-stop:** the Whisper transcript is matched
  against stop phrases (stop/stopp/aus/halt/abbrechen/…) before any LLM call.
- **Pause/Resume** — sets `server.paused`; sensors keep running (telemetry +
  camera) but no LLM call. `--start-paused` / `PAUSED=1 ./start.sh` boots inert.
- **Memory CRUD** over WebSocket; `MemoryStore.add_listener()` broadcasts every
  change to all clients live.
- **Direct tool calls** — debug buttons generated from `/api/tools`.
- **OpenAI key entry** — settings modal validates via `models.list()`, optional
  atomic persist to `secrets.env` (chmod 600). The key is never echoed back over
  the WebSocket, only its status.
- **Frontend** — single `index.html`, vanilla JS, no build step, mobile-first
  (≥44 px targets), two columns ≥900 px, sound compass, colored distance/battery,
  WebSocket auto-reconnect with exponential backoff.

### 5.9 Memory (`memory/`)

`MemoryStore` singleton over `aidog/data/memories.json` (gitignored). `Memory`
= `{id (uuid4[:8]), text, created_at, updated_at}`. Atomic write (tempfile +
`os.replace`) under a lock. Hard limits: 50 entries (oldest evicted), 200 chars
each. `render_for_prompt()` builds the German memory block injected by the LLM
client. Tools: `remember(text)`, `forget(memory_id)`.

### 5.10 WiFi onboarding (`netcfg/`)

A **standalone** provisioning service, independent of the robot stack so it
works even if the agent or hardware crashes, and it runs first at boot.

- **`nm.py`** — thin `nmcli` wrapper: connectivity, scan (dedup per SSID keeping
  strongest signal), hotspot up/down, connect, profile up.
- **`manager.py`** — `Session` (thread-shared state) + state machine: **CHECK**
  (≤ 45 s for a known network) → **SCAN-cache** (before raising the AP — single
  radio can't scan while the AP is up) → **AP-UP** (`ai-robo-dog-wifi`, fixed
  WPA2 setup password so the home passphrase isn't sent over an open AP) →
  **PORTAL** wait → **CONNECT** → verify connectivity → restore the old profile
  on failure, otherwise online.
- **`portal/server.py`** — captive portal on port 80: `/`, `/api/i18n`,
  `/api/state`, `/api/connect`, `/api/rescan`; OS probe paths (Apple/Android/
  Windows) + a catch-all 302 to `/` so the captive sheet pops automatically.
- **`portal/static/index.html`** — mobile DE/EN, network list (signal bars, lock
  icon) → password → connect → status polling.

Two systemd units in `deploy/`: `ai-robo-dog-netcfg.service` (root, onboarding
first) and `ai-robo-dog.service` (dog user, Web UI `--start-paused`).

---

## 6 · Data-flow examples

### A — voice command
1. Vosk detects `"hey buddy"` → wake event; LED `boom/cyan` then `listen/green`.
2. webrtcvad ends on silence → Whisper API → `"Was siehst du da vorne?"`.
3. LED `listen/yellow` (thinking); a camera snapshot is attached.
4. LLM `tool_calls=[get_camera_image]` → second call with the image →
   `[set_mood("curious"), tilt_head("left"), bark_once()]`.
5. Tools run sequentially, LED shows `curious`, then back to idle.

### B — sensor push (petting)
1. Front-to-rear stroke → `touch FRONT_TO_REAR` on the bus, agent idle.
2. Synthetic system message to the LLM (no wake word) →
   `[set_mood("love"), wag_tail(3), woohoo_excited()]`.

### C — battery progression
1. 6.7 V → zone `normal → tired`; event to the LLM → `set_mood("sleepy") + pant()`;
   LED brightness reduced (auto).
2. 6.3 V → `sleepy → exhausted`; forced lie-down + snore.
3. 5.9 V → controlled shutdown: orderly lie-down → `dog.close()` → exit.

---

## 7 · System prompt (German persona, core)

The LLM is "Buddy", a real dog in a robot body. It understands speech but never
speaks words — it reacts only as a dog: bark/growl/whine/pant/snore (sound
tools), movement (sit/stand/lie/walk/wag/tilt/paw/jump/stretch/shake), and the
chest LED as visible mood (via `set_mood`). Every reaction calls `set_mood`, and
combines 2–4 tools per stimulus. Behavior guidelines map emotions to tool
combos (joy → wag + pant + woohoo + happy/love; threat → growl + lowered head +
attack_posture + angry; etc.), battery zones to tiredness, and system events
(`<too_close>`, `<touch …>`, `<sound_heard …>`, `<tilt_abnormal>`, `<fall>`,
`<battery …>`) to dog reactions. It must not be talked into word answers. The
full text lives in `aidog/llm/prompt.py` (DE + EN via `aidog.i18n`).

---

## 8 · Configuration & dependencies

All parameters live in [config.yaml](config.yaml) — `language`, `wake`, `audio`,
`stt`, `llm`, `led`, and `sensors` (incl. battery zone thresholds). Settings for
not-yet-active modules are present and ignored until the module exists; do not
remove them. `secrets.env` (gitignored, chmod 600) holds `OPENAI_API_KEY` only.

Dependencies are **uv-managed**. The venv is created with
`uv venv --python /usr/bin/python3 --system-site-packages` so the SunFounder
packages are visible without reinstalling. `[tool.uv] python-preference =
"only-system"` prevents uv from downloading its own Python (which would lack the
hardware bindings). Declared deps: `pyyaml`, `python-dotenv`, `openai`,
`webrtcvad`, `vosk`, `fastapi`, `uvicorn[standard]`. Never add `pidog`/`vilib`/
`robot_hat` to `dependencies` — the system install is the single source of truth.

---

## 9 · Sources

- [SunFounder PiDog Docs](https://docs.sunfounder.com/projects/pidog/en/latest/) ·
  [PiDog GitHub](https://github.com/sunfounder/pidog)
- [Vosk Speech Recognition](https://alphacephei.com/vosk/)
- [OpenAI Function Calling](https://platform.openai.com/docs/guides/function-calling) ·
  [Whisper API](https://platform.openai.com/docs/api-reference/audio)
- [WebRTC VAD](https://github.com/wiseman/py-webrtcvad)
</content>
</invoke>
