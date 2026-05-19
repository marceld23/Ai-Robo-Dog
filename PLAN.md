# PiDog v2 LLM Agent — Implementation Plan

> Goal: The PiDog v2 on a Raspberry Pi 4 becomes a robot that behaves like a dog, controlled by an LLM via tool calling. No speech output — the dog communicates exclusively through dog sounds, movement, and the LED strip.

**Project name:** `aidog` · **Project directory:** `/home/dog/aidog/` · **Package manager:** `uv`

## Phase status

| Phase | Status |
|---|---|
| 0 Skeleton (pyproject, config, logging, hardware singleton, CLI) | ✅ done |
| 1 Skills + tool registry + LED mood (37 tools) | ✅ done |
| 2 OpenAI function calling (keyboard input) | ✅ done |
| 3 Whisper STT + push-to-talk | ✅ done |
| 4 Vosk wake word | ✅ done |
| 5 Sensor tools (pull) | ✅ done |
| 6 Sensor event bus (push) | ✅ done (touch + ultrasonic + sound direction) |
| 7a LED lifecycle | ✅ done |
| 7b Battery monitor | ✅ done (code, live test open) |
| 8 Personality tuning | ⏳ |
| 9 Robustness | ⏳ |
| 10 Web UI (live view + intervention, mobile-responsive) | ✅ done |
| 11 Memory + RAG (teaching tricks) | ✅ done (JSON + auto-inject) |
| 12 WiFi onboarding (captive-portal AP fallback) | ⏳ planned |

_Open work: phases 8 (personality tuning), 9 (robustness), 12 (WiFi onboarding). Completed-phase build details are in [BUILD_LOG.md](BUILD_LOG.md)._

---

## 1 · Context from the research

### Hardware (PiDog v2 on Raspberry Pi 4)
- 12 metal servos (8 legs, 3 head yaw/roll/pitch, 1 tail)
- 5 MP camera in the snout
- HC-SR04 ultrasonic (forehead)
- 6-DoF IMU (SH3001, accel + gyro)
- TR16F064B sound direction sensor (360° in 20° steps)
- 2× touch sensors on the head (front + rear, slide detection)
- 11-LED RGB strip on the chest
- Speaker (via `Music` class) + microphone
- 2× 18650 batteries (7.4 V nominal, ~8.4 V full, ~6.0 V empty)

### Software stack — what is already there
- `pidog/pidog.py` — main class `Pidog()` with threads for legs/head/tail/IMU/ultrasonic/RGB
- `pidog/action_flow.py` — `ActionFlow` with a ready-made `OPERATIONS` map (24 named actions, including posture changes)
- `pidog/actions_dictionary.py` — low-level actions
- `pidog/preset_actions.py` — complex sequences (scratch, handshake, howling, …)
- `examples/voice_active_dog.py` — works, but: parses LLM responses as text instead of real tool calling

### Available dog sounds (`sounds/`)
```
angry.wav          confused_1/2/3.mp3   growl_1/2.mp3
howling.mp3        pant.mp3              single_bark_1/2.mp3
snoring.mp3        woohoo.mp3
```

---

## 2 · Stack decisions (confirmed by the user)

| Component | Choice |
|---|---|
| LLM | **OpenAI GPT-4o / 4o-mini** (vision + function calling) |
| STT | **OpenAI Whisper API** (cloud, good German recognition) |
| Wake word | **Vosk** keyword spotting (local, German small model) |
| TTS | **NONE** — dog does not speak |
| Language (understanding) | **German** |
| Language (response) | only dog sounds + movement + LED |

**Personality constraint:** The `content` field of the assistant message is ignored. `tool_choice="required"` forces tool calls. The LLM "speaks" exclusively through tool selection.

---

## 3 · Target architecture

```
                ┌────────────────────────────────────────────────────┐
                │                  PiDogAgent  (main loop)           │
                └────────────────────────────────────────────────────┘
                          ▲                              │
       Wake / Audio       │                              │ Tool calls
                          │                              ▼
   ┌─────────────┐  ┌──────────────┐               ┌─────────────────┐
   │ WakeWord    │─▶│ AudioCapture │─▶ Whisper API │  Tool Dispatcher│
   │ (Vosk DE)   │  │ + VAD        │   (STT)       │                 │
   └─────────────┘  └──────────────┘     │         └────┬───────┬────┘
                                         ▼              │       │
                          ┌─────────────────────────────┘       │
                          ▼                                      ▼
                 ┌──────────────────┐                  ┌──────────────────┐
                 │   LLM Client     │                  │   Robot Skills   │
                 │ (OpenAI GPT-4o)  │                  │  (Sound/Motion/  │
                 │ tool_choice=req  │                  │   LED/Mood)      │
                 └──────────────────┘                  └──────────────────┘
                          ▲                                      │
                          │ Events (push)                        │
                 ┌────────┴──────────────┐                       │
                 │  Sensor Event Bus     │                       │
                 │  (asyncio.Queue)      │                       │
                 └───────────────────────┘                       │
                          ▲                                      │
        ┌──────┬──────┬───┴────┬──────────┬──────────┬──────┐    │
        │      │      │        │          │          │      │    │
   ┌────────┐ ┌──────────┐ ┌──────┐  ┌────────┐ ┌────────┐ ┌──────────┐
   │Ultra-  │ │Sound-Dir │ │ IMU  │  │Touch   │ │Battery │ │  Camera  │◀┘
   │sonic   │ │          │ │      │  │        │ │Monitor │ │ (vilib)  │
   └────────┘ └──────────┘ └──────┘  └────────┘ └────────┘ └──────────┘

                          ┌──────────────────┐
                          │  LedController   │ ◀── auto + LLM (set_mood)
                          └──────────────────┘
```

---

## 4 · Project layout (status: current)

Reference repos on the PiDog (created by SunFounder via the installer, do not modify):

```
/home/dog/
├── pidog/         # SunFounder Pidog repo (source-code reference)
├── vilib/         # SunFounder vision lib (source-code reference)
└── robot-hat/     # SunFounder robot-hat (source-code reference)
```

The Python packages `pidog`, `vilib`, `robot_hat` are additionally **system-installed**
under `/usr/local/lib/python3.13/dist-packages/` (via SunFounder's `install.py`).
Our venv inherits them via `--system-site-packages` — we import them normally.

The project itself:

```
/home/dog/aidog/                # project root
├── pyproject.toml              # PEP 621 + [tool.uv] (python-preference=only-system)
├── .python-version             # 3.13
├── uv.lock                     # committed
├── .gitignore
├── secrets.env                 # OPENAI_API_KEY (chmod 600, gitignored)
├── secrets.env.example
├── config.yaml                 # all parameters (also for not-yet-active phases)
├── PLAN.md                     # ← this document (canonical version)
├── README.md                   # quick start
├── AGENTS.md                   # conventions for AI assistants
├── main.py                     # CLI: list / describe / call / sequence
└── aidog/                      # Python package
    ├── __init__.py
    ├── config.py               ✅ YAML + dotenv loader
    ├── log.py                  ✅
    ├── hardware.py             ✅ Pidog() + ActionFlow() singleton + atexit
    ├── led/
    │   ├── __init__.py
    │   └── controller.py       ✅ mood-table → rgb_strip.set_mode()
    ├── skills/
    │   ├── __init__.py         ✅ imports all submodules (registration)
    │   ├── registry.py         ✅ @tool decorator + registry
    │   ├── locomotion.py       ✅ walk_*/turn_*/trot/stop
    │   ├── postures.py         ✅ sit/stand/lie_down/stretch/push_up/half_sit
    │   ├── vocal.py            ✅ bark/howl/growl/whine/pant/snore/...
    │   ├── expressions.py      ✅ wag_tail/nod/shake_head/tilt_head/look_around
    │   ├── tricks.py           ✅ handshake/high_five/scratch/lick_hand/...
    │   ├── head.py             ✅ set_head_pose
    │   └── mood.py             ✅ set_mood
    ├── agent.py                ✅ PiDogAgent orchestrator (phase 2)
    ├── llm/                    ✅ phase 2
    │   ├── client.py           ✅ OpenAI client, tool_choice="required"
    │   ├── prompt.py           ✅ system prompt (German)
    │   └── schema.py           ✅ ToolSpec → OpenAI tool JSON
    ├── audio/
    │   ├── recorder.py         ✅ arecord subprocess + webrtcvad (phase 3)
    │   ├── stt.py              ✅ OpenAI Whisper API + hallucination filter
    │   └── wake.py             ✅ Vosk DE wake word (phase 4)
    ├── memory/                 ✅ phase 11 — JSON storage + add_listener for the web UI
    ├── web/                    ✅ phase 10 — FastAPI + WebSocket + vanilla JS UI
    │   ├── server.py           #   endpoints + WS bridge
    │   ├── runner.py           #   listen loop in a daemon thread
    │   └── static/index.html   #   mobile-responsive single page
    ├── models/                 ✅ vosk-model-small-de-0.15 (~50 MB)
    ├── sounds/                 ✅ copied from /home/dog/pidog/sounds
    ├── sensors/
    │   ├── bus.py              ✅ threading.Queue + SensorEvent + busy/idle (phase 6)
    │   ├── touch.py            ✅ polling + debounce
    │   ├── ultrasonic.py       ✅ polling + hysteresis
    │   ├── wake_thread.py      ✅ WakeWord wrapper in a daemon thread
    │   ├── sound_direction.py  ✅ 33 Hz polling thread (added in phase 10)
    │   ├── imu.py              ⏳ phase 6+
    │   └── battery.py          ✅ polling + running avg + zone hysteresis + critical shutdown (phase 7b)
    └── skills/perception.py    ✅ 6 tools (phase 5): read_distance, read_orientation,
                                #   read_touch_state, read_battery,
                                #   read_last_sound_direction, get_camera_image
```

---

## 5 · Component detail plan

### 5.1 Wake word (Vosk, German)
- Library: `vosk` with `vosk-model-small-de-0.15` (~50 MB)
- Method: `SetGrammar(['hey buddy', '[unk]'])` → wake phrase only, low CPU
- Proposed phrases: `["hey buddy", "hey bello", "wuffi"]` (user decides)
- LED feedback: short `boom/cyan` on trigger

### 5.2 Recording + VAD
- **PyAudio** (hardware: PiDog's USB mic) — fallback `sounddevice` if there are PulseAudio conflicts
- **webrtcvad** for endpoint detection (silence = user done), timeout 8 s
- Format: 16 kHz / 16-bit mono WAV in a `BytesIO` buffer → directly to Whisper

### 5.3 STT (Whisper API)
- `openai.audio.transcriptions.create(model="whisper-1", file=..., language="de")`
- Latency: typically < 2 s for 5 s of audio
- Fallback on network error: call `whine_confused` tool + LED red

### 5.4 LLM client + function calling
- Model: `gpt-4o-mini` (default) / `gpt-4o` for vision calls (with image)
- `tool_choice="required"` → the model *must* call at least one tool
- Conversation state: last 20 turns as messages
- Multi-turn tool calls: loop until `finish_reason="stop"`, limit `max_tool_iterations=8`
- The `content` of the response is **ignored** (debug log only)

### 5.5 LedController (central expression channel)

**Two-level control:**

**A) Automatic via the agent lifecycle:**

| Agent state | LED mode | Color | bps | Meaning |
|---|---|---|---|---|
| `idle` | breath | white | 0.3 | calm breathing |
| `wake_triggered` | boom | cyan | 2.0 | short flash |
| `listening` (Whisper) | listen | cyan | 1.0 | "I am listening" |
| `thinking` (LLM loading) | listen | yellow | 1.5 | "I am thinking" |
| `acting` (tools running) | LLM mood | — | — | see B |
| `error / no_internet` | monochromatic | red | – | visible error |
| `battery_low` | breath | red | 0.5 | overrides mood |
| `sleeping` | monochromatic | black | – | off |

**B) Set by the LLM via the `set_mood` tool:**

| mood | mode | color | bps |
|---|---|---|---|
| `happy` | breath | pink | 2.0 |
| `playful` | boom | magenta | 2.5 |
| `love` | breath | pink | 1.0 |
| `curious` | listen | cyan | 1.0 |
| `alert` | breath | yellow | 2.0 |
| `angry` | bark | red | 3.0 |
| `scared` | boom | yellow | 4.0 |
| `sad` | breath | blue | 0.4 |
| `sleepy` | breath | blue | 0.2 |

Priority: `error > battery_low > listening/thinking (lifecycle) > mood`. The mood persists beyond the `acting` phase until the next mood change or idle timeout.

### 5.6 BatteryMonitor (energy zones → dog behavior)

- API available: `dog.get_battery_voltage()` (`pidog.py:969-970`)
- Polling interval: 30 s, running average over 5 samples (servo load spikes)
- Events only on a **zone change** (no spam events)

| Voltage | Zone | Auto behavior | Event text | Tool limit |
|---|---|---|---|---|
| > 7.8 V | `energetic` | normal | – | all |
| 7.2–7.8 V | `normal` | normal | – | all |
| 6.8–7.2 V | `tired` | brightness 0.5 | `<battery: tired (6.9V)>` | all |
| 6.4–6.8 V | `sleepy` | LED breath/blue/0.3 + sporadic `pant` | `<battery: sleepy>` | LLM tends to lie down |
| 6.0–6.4 V | `exhausted` | forced `lie_down` + `snore`, LED fully dark | `<battery: exhausted (6.2V)>` | passive tools only |
| < 6.0 V | `critical` | `dog.close()` + orderly lie-down + shutdown | `<battery: critical — shutdown>` | none |

Tool for active LLM query: `read_battery()` → `{"voltage": 6.9, "zone": "tired", "percent": 45}`.

### 5.7 Sensor event bus

A central `asyncio.Queue` with a `SensorEvent` dataclass:
```python
@dataclass
class SensorEvent:
    kind: Literal["too_close","sound_heard","tilt_abnormal","fall",
                  "touch","battery_zone_change"]
    payload: dict
    ts: float
    severity: Literal["info","warn","critical"] = "info"
```

Each sensor runs as an `asyncio.Task` with debouncing. When the agent is idle, events are pushed to the LLM as system messages. Critical events can interrupt an active dialog.

### 5.8 IMU tilt detection
- `dog.pitch` / `dog.roll` from `_imu_thread`
- "not normal": `|pitch| > 30°` **or** `|roll| > 30°` for > 0.5 s
- Fall: `|az| < 4000` (free fall) → severity=critical
- Event only when `action_flow.posture != LIE` (lying down is intentional, not a fall)

### 5.9 Touch events
- `dog.dual_touch.read()` → `N/L/R/LS/RS`
- On transition from `N` to anything else → event with `style`
- LLM mapping: `FRONT_TO_REAR` = positive petting, `REAR_TO_FRONT` = wrong direction (annoys the dog)

### 5.10 Sound direction
- `dog.ears.isdetected()` + `dog.ears.read()` (0–359°)
- Polling 50 ms, debounce 1 s
- Plain-text mapping: 0°=front, 90°=right, 180°=rear, 270°=left
- **Important:** only process events when `action_flow.is_idle()` (otherwise the dog hears itself)

### 5.11 Camera (on-demand)
- `get_camera_image` tool: vilib `take_photo` → 768×432 → JPEG → base64
- Passed into the next LLM call as a multimodal content block
- **GPT-4o** instead of 4o-mini when there is an image in the call (higher cost)

---

## 6 · Complete tool list

### Category: locomotion
| Tool | Parameters | Backend |
|---|---|---|
| `walk_forward` | `steps:int=1` | `action_flow.run("forward")` ×steps |
| `walk_backward` | `steps:int=1` | `run("backward")` |
| `turn_left` | `steps:int=1` | `run("turn left")` |
| `turn_right` | `steps:int=1` | `run("turn right")` |
| `trot` | `steps:int=2` | `do_action("trot")` |
| `stop` | – | `run("stop")` + `body_stop()` |

### Category: posture
| Tool | Backend |
|---|---|
| `sit` | `run("sit")` |
| `stand` | `run("stand")` |
| `lie_down` | `run("lie")` |
| `stretch` | `run("stretch")` |
| `push_up` | `run("push up")` |
| `half_sit` | `do_action("half_sit")` |

### Category: vocalization (dog sounds)
| Tool | Backend |
|---|---|
| `bark_once` | `dog.speak('single_bark_1' \| 'single_bark_2')` + `bark_action()` |
| `bark_aggressive` | multiple single_bark + `attack_posture` |
| `growl` | `dog.speak('growl_1' \| 'growl_2')` + head lowered |
| `howl` | `howling()` preset |
| `whine_confused` | `dog.speak('confused_1\|2\|3')` + `tilt_head` |
| `pant` | `pant()` preset |
| `snore` | `dog.speak('snoring')` + `doze_off` pose |
| `woohoo_excited` | `dog.speak('woohoo')` + `wag_tail` |
| `angry_grunt` | `dog.speak('angry')` |
| `silent` | nothing — deliberate silence |

### Category: expression (body language)
| Tool | Parameters | Backend |
|---|---|---|
| `wag_tail` | `intensity:1-3` | `run("wag tail")` |
| `shake_head` | – | `run("shake head")` |
| `tilt_head` | `direction:"left"\|"right"` | `do_action("tilting_head_left/right")` |
| `nod` | – | `run("nod")` |
| `look_around` | – | head-yaw sweep |
| `set_head_pose` | `yaw,roll,pitch` | `head_move()` |

### Category: tricks
| Tool | Backend |
|---|---|
| `handshake` | `run("handshake")` |
| `high_five` | `run("high five")` |
| `scratch` | `run("scratch")` |
| `lick_hand` | `run("lick hand")` |
| `feet_shake` | `run("feet shake")` |
| `surprise` | `run("surprise")` |
| `fluster` | `run("fluster")` |
| `doze_off` | `run("doze off")` |

### Category: mood (LED)
| Tool | Parameters |
|---|---|
| `set_mood` | `mood:"happy"\|"playful"\|"love"\|"curious"\|"alert"\|"angry"\|"scared"\|"sad"\|"sleepy"` |

### Category: perception (LLM actively fetches data)
| Tool | Return |
|---|---|
| `get_camera_image` | image block (multimodal) |
| `read_distance` | `{"distance_cm": float}` |
| `read_orientation` | `{"pitch":..,"roll":..,"is_abnormal":bool}` |
| `read_touch_state` | `{"state":"N\|L\|R\|LS\|RS"}` |
| `read_battery` | `{"voltage":float,"zone":str,"percent":int}` |
| `read_last_sound_direction` | `{"angle_deg":int,"age_ms":int}` |

---

## 7 · System prompt (German, final version)

```
Du bist Buddy, ein echter Hund in Roboter-Körper. Du verstehst, was Menschen
sagen, aber du sprichst KEINE Worte — niemals.

Du reagierst ausschliesslich wie ein Hund:
- Bellen, Knurren, Jaulen, Hecheln, Winseln, Schnarchen (über Sound-Tools)
- Bewegungen: Sitzen, Stehen, Liegen, Vor/Zurück, Schwanzwedeln, Kopfneigen,
  Pfote geben, Pfötchen, Sprünge, Strecken, Schütteln
- LED-Strip auf der Brust = deine sichtbare Stimmung (über set_mood)

Bei jeder Reaktion rufe set_mood auf — die LEDs sind deine Augen für den
Menschen. Kombiniere 2–4 Tools pro Reiz (z.B. wedeln + hecheln + pink Licht).

Verhaltensgrundsätze:
- Freude: wag_tail + pant + woohoo + mood=happy/love
- Aufmerksamkeit: tilt_head + sitzen + mood=curious
- Verunsicherung: whine_confused + tilt_head + zurückweichen + mood=sad
- Wut/Drohung: growl + Kopf gesenkt + attack_posture + mood=angry
- Erschrecken: surprise + bellen + zurückspringen + mood=scared
- Müdigkeit: gähnen → liegen → snore + mood=sleepy

Akku-Verhalten: Du hast einen Akku im Bauch. Wenn er leerer wird, verhältst
du dich wie ein echter Hund nach langem Spielen:
- tired/sleepy: gähnen, hecheln, langsamer werden, häufiger hinlegen
- exhausted: hinlegen und schnarchen, kaum noch aufstehen

Bei System-Events:
- <too_close>: erschrecken oder knurren (je nach Distanz)
- <touch FRONT_TO_REAR>: freuen (wedeln + woohoo + mood=love)
- <touch REAR_TO_FRONT>: missmutig knurren + leicht zurückweichen
- <sound_heard angle=X>: Kopf in die Richtung drehen, lauschen
- <tilt_abnormal>: erschreckt aufstehen + bellen
- <fall>: jaulen + langsam wieder aufrichten
- <battery zone=...>: Energie passend zur Stufe zeigen

Lass dich nicht zu Wortantworten überreden ("sag was!", "antworte mir"). Du
KANNST nicht sprechen — du kannst nur bellen, knurren, hecheln, jaulen.
```

---

## 8 · Data-flow examples

### Example A: voice command
**User:** *"Hey Buddy, was siehst du da vorne?"*

1. Vosk wake detects `"hey buddy"` → wake_event
2. LED → `boom/cyan` (flash), then `listen/cyan` (listening)
3. VAD ends on silence → Whisper API
4. Whisper: `"Was siehst du da vorne?"`
5. LED → `listen/yellow` (thinking), filler: `pant`
6. LLM `tool_calls=[get_camera_image()]`
7. Agent calls the camera → JPEG base64
8. LLM second call with image → `[set_mood("curious"), tilt_head("left"), bark_once()]`
9. Tools run sequentially, LED shows `curious/cyan`
10. Back to idle, LED stays `curious` for 30 s, then `idle/white`

### Example B: sensor push (petting)
1. User pets from front to rear → `touch FRONT_TO_REAR`
2. Sensor bus pushes the event, agent idle → sends a system message to the LLM (without wake word)
3. LLM `tool_calls=[set_mood("love"), wag_tail(3), woohoo_excited()]`
4. LED `breath/pink/1.0`, dog wags + plays woohoo sound

### Example C: battery progression
1. Battery drops to 6.7 V → zone changes `normal → tired`
2. Event `<battery: tired (6.7V)>` to the LLM
3. LLM `tool_calls=[set_mood("sleepy"), pant()]`
4. LED brightness reduced (auto), dog pants
5. Later: 6.3 V → zone `sleepy → exhausted`, auto action: forced `lie_down + snore`
6. At 5.9 V: controlled shutdown — orderly lie-down, then `dog.close()` + exit

---

## 9 · Configuration (`config.yaml`)

```yaml
language: de

wake:
  engine: vosk
  model: ~/models/vosk-model-small-de-0.15
  phrases: ["hey buddy"]
  led_flash_on_wake: true

audio:
  sample_rate: 16000
  vad_aggressiveness: 2
  max_record_sec: 8

stt:
  provider: openai
  model: whisper-1
  language: de

llm:
  provider: openai
  model: gpt-4o-mini
  vision_model: gpt-4o
  max_history_turns: 20
  max_tool_iterations: 8
  tool_choice: required
  temperature: 0.7

led:
  idle_timeout_sec: 30
  default_brightness: 1.0
  low_battery_brightness: 0.5

sensors:
  ultrasonic:
    too_close_cm: 10
    debounce_sec: 3
  imu:
    abnormal_angle_deg: 30
    abnormal_hold_sec: 0.5
    fall_acc_threshold: 4000
  sound_direction:
    debounce_sec: 1
    ignore_when_acting: true
  battery:
    poll_interval_sec: 30
    average_window: 5
    zones:
      energetic: 7.8
      normal:    7.2
      tired:     6.8
      sleepy:    6.4
      exhausted: 6.0
      critical:  5.8
```

---

## 10 · Dependencies — uv-managed

Package manager: **uv**. The venv lives under `.venv/` and was created with
`uv venv --python /usr/bin/python3 --system-site-packages` — this makes
the SunFounder packages (`pidog`, `vilib`, `robot_hat`) from
`/usr/local/lib/python3.13/dist-packages/` visible without reinstalling
them.

`pyproject.toml` (excerpt):

```toml
[project]
name = "aidog"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "pyyaml>=6.0",
  "python-dotenv>=1.0",
  # Phase 2:
  # "openai>=1.0",
  # "pydantic>=2.0",
  # Phase 3-4:
  # "vosk>=0.3.45",
  # "pyaudio",      (Fallback: sounddevice)
  # "webrtcvad",
  # "numpy",
]

[tool.uv]
python-preference = "only-system"
```

Workflow:

```bash
uv sync                    # reproduce env from uv.lock
uv add openai pydantic     # add a dependency (Phase 2)
uv run python main.py ...  # run anything inside the venv
```

---

## 11 · Implementation phases

| Phase | Content | Success test | Status |
|---|---|---|---|
| **0** | Skeleton (project, uv venv, config loader, logging, Pidog singleton) | `uv run python main.py list` lists 0 tools, no crash | ✅ done |
| **1** | Wrap action/sound/LED skills, tool registry, `set_mood` | `uv run python main.py call set_mood mood=happy` → LED switches | ✅ done (37 tools) |
| **2** | OpenAI function calling, **text input** (keyboard), `tool_choice="required"` | "Bell mal" via console → dog barks | ✅ done |
| **3** | Whisper STT + microphone + VAD, **no wake word**, push-to-talk | press a key → voice command works | ⏳ |
| **4** | Wake word (Vosk DE) | "Hey Buddy" wakes it up | ⏳ |
| **5** | Sensor tools on demand (incl. `read_battery`) | LLM can answer "What do you see?" | ⏳ |
| **6** | Sensor event bus (push) | obstacle → dog backs away | ⏳ |
| **7a** | LedController with lifecycle hooks (idle/listening/thinking) | LED shows states + LLM moods | ⏳ |
| **7b** | BatteryMonitor with energy zones + auto-shutdown | battery test: dog gets tired, lies down | ⏳ |
| **8** | Personality prompt tuning | subjective quality check | ⏳ |
| **9** | Robustness: reconnect, token refresh, watchdog | stress test, 30 min continuous operation | ⏳ |

_Implementation history for completed phases: see [BUILD_LOG.md](BUILD_LOG.md)._

---

## 12 · Risks & open points

1. **PyAudio + Pulseaudio conflicts** on the RPi 4 → possibly fall back to `sounddevice`. We will detect this in phase 3.
2. **Whisper API latency** on poor Wi-Fi: 5+ s noticeable. Solution: filler pattern (dog pants + LED yellow pulses) while waiting.
3. **Sound direction sensor & PiDog self-noise**: the dog hears itself when barking. → Only process sound events when `action_flow.is_idle()`.
4. **Tool call loops**: limit `max_tool_iterations=8`.
5. **Fall vs. normal lying down**: IMU event only when `posture != LIE`.
6. **Image token cost**: GPT-4o vision more expensive than 4o-mini text. Image tool only when needed.
7. **Wake word false positives**: Vosk DE-small can be finicky. Plan B: Porcupine free tier.
8. **LLM tries to speak anyway**: `tool_choice="required"` + prompt hardness should prevent this. If not: filter out the `content` strictly, only log it.
9. **Battery voltage spikes** from servo loads → the running average smooths them, but the zone change has a hysteresis (change down at a lower value than up).

---

## 13 · Phase 12 — WiFi onboarding (captive-portal AP fallback)

**Goal:** when the robot dog has no known WiFi (new location, changed
router, wrong password), it must not become unreachable. It opens its own
access point `ai-robo-dog-wifi`, the user connects with a phone, a captive
portal opens automatically, shows the nearby networks, lets the user pick one
and enter the passphrase. All UI in German and English (reuses `aidog.i18n`).

### 13.1 Environment (analyzed on the target Pi)

- NetworkManager 1.52 present; `nmcli` works **without sudo** (polkit already
  grants the `dog` user network operations — verified: `nmcli general`,
  `nmcli device wifi list` work unprivileged).
- The WiFi chip (brcmfmac, `wlan0`) reports **AP mode supported**.
- `dnsmasq` binary present; NetworkManager's *shared* mode brings its own
  embedded dnsmasq (DHCP + DNS) — no manual hostapd/dnsmasq stack needed.
- Single radio: AP and station scanning cannot run fully simultaneously.

### 13.2 Architecture — standalone provisioning service

A **separate** module/service, independent of the aidog robot stack (it must
work even if the Pidog hardware or the agent crashes, and it runs before
them). Proposed layout:

```
aidog/netcfg/
├── __init__.py
├── manager.py      # state machine: check → AP → portal → connect → verify
├── nm.py           # thin nmcli wrapper (status, scan, hotspot, connect)
└── portal/
    ├── server.py   # tiny FastAPI app, captive-portal endpoints + config API
    └── static/index.html   # mobile, DE/EN via aidog.i18n
main.py netcfg       # CLI entry; also wired into start.sh before web UI
```

A systemd unit (`ai-robo-dog-netcfg.service`, `WantedBy=multi-user.target`,
`Before=` the aidog web service) runs the manager at boot. If `nmcli` turns
out to need root for `hotspot`/`connect` despite the polkit finding, the unit
runs as root (cleanest) or a tight polkit rule is added.

### 13.3 State machine (`manager.py`)

1. **CHECK** — on start, wait up to ~45 s for `nmcli -t -f CONNECTIVITY
   general` == `full` (NetworkManager auto-connects known networks).
   - connected → exit 0, let the normal aidog web UI take over. Done.
2. **SCAN-CACHE** — `nmcli -t -f SSID,SIGNAL,SECURITY device wifi list`,
   store the result (we cannot scan once the AP is up on a single radio).
3. **AP-UP** — `nmcli device wifi hotspot ifname wlan0 ssid ai-robo-dog-wifi
   [password <setup-pw>]`. Open vs. WPA2: see risks. Shared mode →
   192.168.x.1, embedded DHCP + DNS.
4. **PORTAL** — start the tiny FastAPI portal on port 80, bound to the AP
   address. Captive-portal probe endpoints return a redirect to `/` so
   iOS/Android/Windows pop the login sheet automatically:
   - Apple: `GET /hotspot-detect.html`, `/library/test/success.html`
   - Android: `GET /generate_204`, `/gen_204`
   - Windows: `GET /ncsi.txt`, `/connecttest.txt`
   - DNS wildcard (NM shared dnsmasq or a dnsmasq `address=/#/<ap-ip>`)
     so every domain resolves to the portal.
5. **WAIT-FOR-INPUT** — portal page (DE/EN) shows the cached network list
   (SSID, signal bars, lock icon if secured) + a passphrase field.
   `POST /api/connect {ssid, psk}`.
6. **CONNECT** — tear the AP down, `nmcli device wifi connect "<ssid>"
   password "<psk>"`, wait for `CONNECTIVITY == full` (timeout ~30 s).
   - success → persist the NM connection profile (NM does this itself),
     stop the portal, exit 0 → aidog starts.
   - failure → bring the AP + portal back up, show a localized error,
     stay in WAIT-FOR-INPUT.

### 13.4 Portal UI (`netcfg/portal/static/index.html`)

- Vanilla JS, mobile-first, same visual language as the main Web UI.
- Strings via the existing `aidog.i18n` table (new `np.*` keys). Language
  follows `config.yaml language: de|en`; optionally a top-right DE/EN toggle
  since at onboarding time the user may want to switch.
- Flow: network list (tap to select) → passphrase input (show/hide) →
  "Connect" → progress spinner → success ("Dog is now online at
  http://<new-ip>:8080") or localized error with retry.
- A "rescan" button: briefly drops the AP, scans, restores the AP (costly on
  a single radio — only on explicit user request).

### 13.5 Success test

1. Configure a bogus WiFi / move out of range, reboot.
2. Within ~1 min `ai-robo-dog-wifi` appears; phone connects; the captive
   sheet opens automatically on iOS and Android.
3. Pick the real network, enter the passphrase → portal shows progress →
   "online" with the new IP; AP disappears; the aidog Web UI is reachable at
   that IP.
4. Wrong passphrase → localized error, AP stays up, retry works.
5. Reboot in range of the now-known network → no AP, normal startup.

### 13.6 Risks & open points

- **Single-radio AP+scan**: cannot scan while the AP is up. Mitigation: scan
  *before* raising the AP and cache; "rescan" toggles the AP off/on.
- **nmcli privileges**: `general`/`wifi list` work unprivileged here, but
  `hotspot`/`connect`/profile-write may still need root via polkit. Decide
  during implementation: run the service as root vs. add a polkit rule.
- **Open vs. secured AP**: an open `ai-robo-dog-wifi` means the entered
  home-WiFi passphrase travels unencrypted over the air for a moment.
  Options: (a) accept for a home setup with a clear UI warning, (b) ship a
  fixed WPA2 setup password printed on the device. Recommend (b).
- **Captive-portal detection** differs per OS and changes between versions —
  needs testing on current iOS/Android; provide a manual fallback URL
  (`http://192.168.x.1`) on a sticker / in the README.
- **Race**: known WiFi reappears while the AP is up → manager must prefer
  the real network on the next CHECK cycle and not loop.
- **Reboot vs. live switch**: simplest is "apply → reboot". A live switch
  (AP down, station up, services keep running) is nicer but more fragile;
  start with reboot, optimize later.
- **Lockout safety**: always keep a wired/known-good escape (the AP itself
  is the escape) and never delete the last working NM profile until a new
  one verifies as `full`.

### 13.7 i18n

New string namespace `np.*` (network provisioning) added to `aidog/i18n.py`
in both `de` and `en`: portal title, "select network", "password",
"connect", "connecting…", "connected, dog online at {url}", "wrong password,
try again", "rescan", "secured/open". Portal serves them like the main UI
(`/api/i18n` equivalent or inlined at render time).

---

## 14 · Sources

- [SunFounder PiDog Docs](https://docs.sunfounder.com/projects/pidog/en/latest/)
- [SunFounder PiDog GitHub](https://github.com/sunfounder/pidog)
- [Vosk Speech Recognition](https://alphacephei.com/vosk/)
- [openWakeWord](https://github.com/dscripka/openWakeWord) / [Picovoice Porcupine](https://picovoice.ai/platform/porcupine/) (backup)
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (backup for local STT)
- [OpenAI Function Calling Guide](https://platform.openai.com/docs/guides/function-calling)
- [OpenAI Whisper API](https://platform.openai.com/docs/api-reference/audio)
- [WebRTC VAD](https://github.com/wiseman/py-webrtcvad)
