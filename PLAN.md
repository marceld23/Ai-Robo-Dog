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

### What was built in phase 2

- `openai>=2.36` via `uv add` in `pyproject.toml`
- `aidog/llm/schema.py` — `ToolSpec` → OpenAI function-calling JSON schema. `Literal[...]` becomes `enum`, default values appear as `default`, the required list is set.
- `aidog/llm/prompt.py` — system prompt (German dog persona text from § 7) as a module constant.
- `aidog/llm/client.py` — `LLMClient.run_turn(text)`:
  - First iteration with `tool_choice="required"`, then `"auto"`.
  - Multi-turn loop until there are no more `tool_calls` or `max_tool_iterations` is reached.
  - History is trimmed at the oldest user turn (default 20).
  - The tool executor is injected → hardware code testable via a mock.
- `aidog/agent.py` — `PiDogAgent.chat(text)` dispatches tool calls against the `aidog.skills` registry, formats the result as a list of readable lines.
- `main.py chat` — REPL `you> ...` with Ctrl+D/Ctrl+C; `--say "text"` for one-shot tests.

Smoke test (mock executor, no hardware touch, real API call):
*"Hey Buddy, bell mal!"* → 3 iterations, tools: `bark_once()`, `set_mood(mood='happy')`, then a clean stop.

### What was built in phase 10

**Web UI on `:8080`, mobile-responsive, runs via `./start.sh` (or `uv run python main.py web`).**

- **Backend** (`aidog/web/server.py` + `runner.py`):
  - FastAPI + Uvicorn as an HTTP/WebSocket server, the listen loop runs in a daemon thread and bridges to the WebSocket via `asyncio.run_coroutine_threadsafe`
  - Endpoints: `/` (HTML), `/api/tools`, `/api/state`, `/api/telemetry`, `/api/camera.jpg` (cached 1.5 s), `/ws` (bidirectional)
  - Telemetry loop pushes a sensor snapshot to the frontend every 2 s (distance, pitch/roll, battery zone, LED state, sound direction with age)
  - **Telemetry to the LLM**: on every turn the current values are injected as a second system message into the LLMClient (distance, tilt, battery zone, last sound). Buddy always has the sensor context without the LLM needing to call extra `read_*` tools
  - **Auto image on every turn** as already in the listen CLI — multimodal GPT-5.4-mini call
- **Stop**: a single button (unified by the user instead of soft/hard) — `body_stop` + `head 0,0,0` + `flow.run("stand")` + LLM loop abort + LED → idle
- **Voice stop**: after the Whisper transcript the text is checked against `_STOP_PHRASES` (stop, stopp, aus, halt, abbrechen, schluss, …). On a match → no LLM call, straight to a neutral pose
- **Pause**: sets the `server.paused` event; sensors keep running (telemetry + camera stream) but no LLM call. Visible via the LED (`paused` lifecycle, magenta breath 0.4 bps) and the web UI button ("▶ Weiter")
- **Memory CRUD** over WebSocket (add/edit/delete/list). `MemoryStore.add_listener()` broadcasts every change immediately to all clients
- **Direct tool calls**: a collapsible debug area with buttons from `/api/tools`, categorized. Per tool the parameters are requested via `prompt()`
- **OpenAI key entry**: the settings modal validates the key via `client.models.list()`. Optionally persisted in `secrets.env` (atomic write + chmod 600)
- **Frontend** (`aidog/web/static/index.html`, single file):
  - Vanilla JS, no build step, mobile-first (44 px tap targets, viewport meta)
  - Live log filters out telemetry events (too spammy), highlights `llm_input` with a green border + accent
  - Sound compass (CSS-only, needle rotates to the direction) shows values up to 10 min old with a fade
  - Distance/battery are colored: green/yellow/red depending on the threshold
  - Camera image refreshes every 2 s, pausable
  - Auto-reconnect on WebSocket drop with exponential backoff
  - Layout switches to two columns on desktop ≥900 px (log/input/tools left, camera/telemetry/memory right)
- **`start.sh`** wrapper: kill old hangers, set `SDL_AUDIODRIVER=pulse`, foreground or `--background` with logs in `/tmp/aidog.log`

**Side catch in phase 6**: `aidog/sensors/sound_direction.py` — a dedicated 33 Hz polling thread, because the voicehat detect signal is only active for ms and was almost always missed in the 2 s telemetry loop. Stores the last angle + timestamp in `LATEST` (read by the server).

**Side catch in the LLM path**: `read_distance` and telemetry now return `null` instead of -1/-2 when the ultrasonic gets no echo — otherwise the LLM treated "obstacle 1 cm in front of me" as valid.

**Camera auto-recovery**: if `Vilib.img` is still None after 0.5 s (Pi camera frontend timeout, typical with a wobbly ribbon cable), `camera_snapshot_b64` tries `camera_close + camera_start` once and retries.

### What was built in phase 11

- `aidog/memory/__init__.py` — `MemoryStore` singleton, JSON file `aidog/data/memories.json` (gitignored). Atomic write via tempfile + os.replace, threading.Lock against concurrent writes.
- `Memory` dataclass with `id` (uuid4 [:8]), `text`, `created_at`, `updated_at` (ISO 8601 UTC).
- Hard limits: 50 entries max (oldest evicted when full), 200 characters per text. Prevents prompt bloat.
- `MemoryStore.render_for_prompt()` builds a German system-message block with all memories + clarification that the persona rule "no word answers" must not be overridden.
- `LLMClient.run_turn` injects this automatically as the second system message before every call. Token cost ~50 per memory, at 50 entries ~2500 tokens overhead — with gpt-5.4-mini 0.0019 USD per call (acceptable).
- `aidog/skills/memory.py` — new category `memory`:
  - `remember(text)` → adds, returns `{id, text}`
  - `forget(memory_id)` → deletes, returns `{deleted, id}`
- `MemoryStore` has `add_listener()` + `_notify()` for the web UI live broadcasts in phase 10. Currently unused.

**Verified run:** "hey buddy, merk dir: wenn ich ‚wo ist der Ball' sage, setz dich und wedle" → Buddy calls `remember(text)`. The JSON file contains the memory. On the next turn (even after a restart) the memory automatically appears in the system prompt → Buddy reacts consistently.

### What was built in phase 7b

- `aidog/sensors/battery.py` — polling thread, every 30 s `dog.get_battery_voltage()`, running average over 5 samples (against servo voltage spikes).
- Zone mapping from `config.yaml.sensors.battery.zones` (default: energetic > 7.8 > normal > 7.2 > tired > 6.8 > sleepy > 6.4 > exhausted > 6.0 > critical < 5.8).
- **50 mV hysteresis** when changing to a lower zone — prevents ping-pong from load spikes.
- On a real zone change: `SensorEvent(kind="battery_zone_change", payload={voltage, zone, previous}, severity="warn"|"critical")` onto the bus → the LLM gets it in the listen loop and reacts dog-tired / dog-lively (prompt extended).
- **LED auto:** zone in {tired, sleepy, exhausted, critical} → `set_brightness(0.5)`. Zone in {sleepy, exhausted} → additionally `set_lifecycle("battery_low")` (red breathing).
- **Critical shutdown in the sensor thread (deterministic, not via the LLM):** `dog.do_action("lie")` + LEDs off + `hardware.shutdown()` + `os._exit(0)`. Guarantees a clean lie-down before Pidog drives the servos through.

**Live test:** not yet run because the battery is currently in the normal zone (7.54 V). Smoke: zone mapping + module import OK. Real zone changes will appear with longer use.

### What was built in phase 7a

`aidog/led/controller.py` extended with a lifecycle override alongside the already-present mood state. Effective display by priority:

```
error > battery_low > lifecycle (wake/listening/thinking/sleeping)
                    > mood (from the LLM via set_mood)
                    > default-idle (breath/white/0.3)
```

| Lifecycle state | Spec | Meaning |
|---|---|---|
| `idle` | (transparent → mood/default) | waiting for a trigger |
| `wake` | boom/cyan/2.0 | "hey buddy" just detected |
| `listening` | listen/**green**/1.5 | speak now — user choice instead of cyan so it is clearly distinct from the wake cyan |
| `thinking` | listen/yellow/1.5 | Whisper/LLM running, do not speak |
| `error` | monochromatic/red/0 | handler crash; stays visible for 1.5 s |
| `battery_low` | breath/red/0.5 | phase 7b sets this later |
| `sleeping` | monochromatic/black/0 | off |

`set_lifecycle(state)` and `set_mood(mood)` set independently, `_apply_locked()` computes the effective spec. The mood from the LLM stays in memory and "comes back" as soon as the lifecycle override drops.

**Listen loop**:
- `idle` at startup
- `wake` on a match → cue plays → 250 ms mic wakeup pause (was in the same step: recordings delivered too few voiced frames because the mic was dead for the first 200 ms after paplay)
- `listening` during `record_until_silence`
- `thinking` during Whisper + LLM
- `idle` back after tool execution
- `error` for 1.5 s if the handler crashes

**Bonus fix:** `Recording.has_voice` threshold from 600 ms (30 frames) to **300 ms** (15 frames) — the voicehat mic often delivers only 300-500 ms usable for short commands like "bell mal".

### What was built in phase 6

**Threading-based** (instead of asyncio from the original plan § 5.7 — more pragmatic for the sync Pidog API). First set: **touch + ultrasonic** (IMU/sound direction/battery follow iteratively).

- `aidog/sensors/bus.py`:
  - `SensorEvent` dataclass: `kind`, `payload`, `ts`, `severity`
  - `SensorBus` singleton: `queue.Queue` + `threading.Event` (`busy`/`idle`)
  - `emit()` drops while busy, `emit_force()` for critical events (later for falls etc.)
  - `set_busy()` / `set_idle()` wrap each event handler in the consumer
- `aidog/sensors/touch.py` — polling 50 ms, debounce 1 s, maps `dual_touch.read()` → `touch` event with `style` (N/L/R/LS/RS)
- `aidog/sensors/ultrasonic.py` — polling 200 ms, hysteresis (enter zone <10 cm, leave ≥15 cm) → `too_close` event with severity `warn`
- `aidog/sensors/wake_thread.py` — wraps `WakeWord` in a daemon thread. Pauses while the bus is busy (otherwise an arecord conflict with the recording arecord). After a match it waits briefly for the consumer to set busy before starting the next `wait_for_wake`.
- `main.py listen` reworked: all three sensor threads run in parallel, the loop blocks on `bus.get()` and dispatches via `event.kind`:
  - `wake` → wake cue + record_until_silence + Whisper + camera snapshot + LLM
  - `touch` / `too_close` → synthetic user text `<sensor: kind ...>` + camera snapshot + LLM
  - A crash in the handler no longer aborts the loop (wrapped with try/except, busy/idle is cleanly reset)
- `aidog/llm/prompt.py` — sensor event reactions detailed per `style` (FRONT_TO_REAR=love, REAR_TO_FRONT=alert, …) and distance thresholds (<5 cm = scared, <10 cm = angry).

**Two bugs uncovered + fixed in the first live test:**
- `agent._dispatch` threw away the tool return value and always returned `"ok"` → the camera sentinel `__IMAGE_B64__:…` never reached the LLMClient. Now: `result if not None else "ok"`. This now also makes the `get_camera_image` called by the LLM **itself** work (not just the auto image from the listen loop).
- When the LLM delivered neither content nor tool_calls in an iteration, an empty `{"role": "assistant"}` was still written to the history — OpenAI rejects this in the next call with HTTP 400 `content: null`. Now: only append if content **or** tool_calls are present.

**Verified behavior:** petting the head triggers Buddy's reaction, a hand in front of the snout (< 10 cm) triggers a `too_close` event, "hey buddy …" triggers the wake path. All three run in parallel, Buddy decides the tool combination per event itself.

### What was built in phase 5

- `aidog/skills/perception.py` — 6 new tools, category `perception`:
  - `read_distance` → `{distance_cm}` from `dog.read_distance()`
  - `read_orientation` → `{pitch_deg, roll_deg, is_abnormal}` with `|angle| > 30°` threshold
  - `read_touch_state` → `{state: N|L|R|LS|RS}` from `dog.dual_touch.read()`
  - `read_battery` → `{voltage, zone, percent}` with zone mapping from `config.yaml.sensors.battery.zones` and 0-100% linear between 6.0 V and 8.4 V
  - `read_last_sound_direction` → `{angle_deg, age_ms}` (age_ms=-1 when nothing is currently detected; real age only in phase 6 when the push bus stores the events)
  - `get_camera_image` → vilib snapshot, **resize to max 512px**, JPEG q=75, base64. Returns sentinel string `__IMAGE_B64__:<base64>`
- `aidog/hardware.py` extended:
  - `camera_snapshot_b64()` with lazy vilib init + cv2 resize. **detail="low"** in the vision call (85 tokens fixed → ~$0.0001 per image with gpt-5.4-mini)
  - `_kill_stale_gpio_holders()` runs on the first `dog()` init and kills hung predecessor processes
  - Patch for the `robot_hat.device._adc_obj` NameError (bug: `global` without module init), we set it to `None`
  - `_shutdown` now also closes `Vilib.camera_close()`
- `aidog/llm/client.py` — sentinel pattern for images:
  - If a tool result starts with `__IMAGE_B64__:`, the client builds two messages: `tool` with marker text and immediately after `user` with an `image_url` content block (`detail="low"`)
  - `_needs_vision` flag automatically switches to the `vision_model`
  - `run_turn(user_text, image_b64=None)` optionally accepts an image along with the user text — it is packed as multimodal user content and triggers `vision_model`
- `aidog/llm/prompt.py` — system prompt extended: for camera images Buddy reacts depending on the content (human → wag, obstacle → back away, animal → play, dark → confused), never just `silent()`. Plus an explicit note that an image is automatically included with every voice command.
- `aidog/agent.py` — `chat(user_text, image_b64=None)` passes the image through.
- `main.py listen` — after the Whisper transcript, a `camera_snapshot_b64()` is taken before the LLM call and sent along as an image. If the snapshot fails, the turn continues without an image.
- `config.yaml`: `llm.model = gpt-5.4-mini`, `vision_model = gpt-5.4-mini` (multimodal, same chat history for text and vision turns).

**Verified reads:** distance 57.1 cm, orientation 0/0/False, touch N, battery 7.54 V (normal, 64 %), sound direction 232°. Camera + LLM vision: successful end-to-end run with `chat --say "Was siehst du?"` → `get_camera_image + tilt_head + bark_once + set_mood(curious)` and a `listen` loop with auto image.

### What was built in phase 4

- `vosk` via `uv add`, German small model (`vosk-model-small-de-0.15`, ~50 MB) downloaded to `aidog/models/` (gitignore candidate).
- `aidog/audio/wake.py` — `WakeWord(model_path, phrases)`:
  - `KaldiRecognizer` with a fixed grammar `[*phrases, "[unk]"]` → low CPU, no free ASR output
  - `wait_for_wake()` spawns `arecord` and streams 4000-byte chunks until a phrase is detected
  - Path resolver: relative to the project root (not cwd), absolute stays absolute
- `main.py listen` reworked: touch PTT removed entirely, the wake loop is the only trigger.
- Wake cue: a short `single_bark_2` (~0.5 s) as an acoustic acknowledgement, configurable via `wake.cue_sound`.
- **Status indicator via head position** (user request):
  - Idle / wake expected: neutral `[0,0,0]`
  - Recording done, audio → Whisper: head left `[0,-25,0]`
  - Text received, text → LLM: head right `[0,25,0]`
  - LLM response done: back to neutral
  - All `head_move` calls are non-blocking (`immediately=True`, no `wait_head_done`) — the servo runs in parallel with the network call.
- VAD tuning after the first test (recording stopped too early because the user pause between wake and command > silence tolerance):
  - `silence_end_sec`: 1.0 → 1.5
  - `min_voice_sec` (new): 0.3 — silence termination only kicks in after ≥300 ms of real speech
- `config.yaml` `wake:`: model path relative (`./models/...`), `phrases: ["hey buddy"]`, `cue_sound: single_bark_2`.

**Test sentences that ran successfully:** "hey buddy, setz dich hin", "hey buddy, bell mal", "hey buddy, wedeln mit dem Schwanz". Whisper latency ~1–5 s depending on audio length.

### What was built in phase 3

- `webrtcvad` via `uv add` (~50 KB native build).
- `aidog/audio/recorder.py` — `record_until_silence()`: spawns `arecord -f S16_LE -r 16000 -c 1 -t raw`, reads 20 ms frames, passes each through webrtcvad. Ends on `silence_end_sec` of silence (default 1.0 s) after the first voice frame or at the latest after `max_record_sec` (default 8.0 s). Returns `Recording(wav_bytes, duration_sec, voiced_frames, total_frames)` — `wav_bytes` is an in-memory WAV with header, passable directly to Whisper. `has_voice` property: ≥30 voiced frames (≥600 ms) as threshold, below that Whisper mostly hallucinates training data.
- `aidog/audio/stt.py` — `WhisperSTT.transcribe(wav_bytes)` calls `client.audio.transcriptions.create(model="whisper-1", language="de")`. Plus `is_likely_hallucination(text)` with a list of the most common Whisper standard hallucinations ("Untertitel der Amara.org-Community", "Vielen Dank fürs Zuschauen", a lone ".", "you", …).
- `main.py listen` — new subcommand:
  1. Pidog hardware init (singleton, shared with `chat`/`call`)
  2. Polling loop (50 ms): `dog.dual_touch.read()` — as soon as `!= 'N'` → start recording
  3. `record_until_silence` → check has_voice → discard on silence
  4. WAV → Whisper → hallucination filter → discard on a match
  5. Text → `PiDogAgent.chat()` → tool calls are executed, output like the `chat` CLI
  6. Re-trigger protection: wait until touch is released again, then back to idle
- `config.yaml` `audio:`: `sample_rate=16000`, `vad_aggressiveness=1` (2 was too strict with the quiet voicehat mic), `max_record_sec=8`, `silence_end_sec=1.0`.

**Hardware findings:**
- The voicehat mic level is very quiet (max ≈ 200/32767 ≈ 0.6 %), Whisper transcribes reliably anyway.
- GPIO20 (PCM_DIN) is sometimes left as a plain input by previous Pidog runs → mic delivers silence. `aidog.hardware._prepare_audio_routing` therefore forces `pinctrl set 20 a0` on every `dog()` init.

**Verified sentences:** "Bellen mal kurz" → `bark_once + set_mood(happy)`; "Setz dich hin!" → `sit + set_mood(curious) + tilt_head(left)`; "Wedeln mit dem Schwanz" → `wag_tail(intensity=3) + set_mood(happy)`. Whisper latency ~1 s typical (for ~3 s audio).

### What was built in phases 0+1

- `pyproject.toml` with `[tool.uv]`, `.python-version=3.13`, `uv.lock` committed
- venv under `.venv/`, `--system-site-packages` for `pidog`/`vilib`/`robot_hat`
- `aidog.config` (YAML + dotenv), `aidog.log` (stdlib logging)
- `aidog.hardware` (Pidog singleton with an atexit `close()` hook)
- `aidog.led.LedController` (mood-table → `rgb_strip.set_mode`)
- `aidog.skills` with a `@tool` decorator, tool registry, 37 tools in 7 categories:
  - **locomotion** (6): walk_forward / walk_backward / turn_left / turn_right / trot / stop
  - **posture** (6): sit / stand / lie_down / stretch / push_up / half_sit
  - **vocal** (10): bark_once / bark_aggressive / growl / howl / whine_confused / pant / snore / woohoo_excited / angry_grunt / silent
  - **expression** (5): wag_tail / shake_head / tilt_head / nod / look_around
  - **trick** (8): handshake / high_five / scratch / lick_hand / feet_shake / surprise / fluster / doze_off
  - **head** (1): set_head_pose
  - **mood** (1): set_mood
- CLI `main.py`: `list` / `describe <name>` / `call <name> k=v...` / `sequence <names...>`

---

## 11.x · Sound pipeline after the uv migration — solved (status 2026-05-15 14:00)

**Status:** ✅ `uv run python main.py call bark_once` plays the bark sound, clean shutdown.

**Three problems found + fixed — all in `aidog/` code, no intervention in `pidog`/`robot_hat`:**

### 1. Internal `sudo` calls in pidog/robot_hat
- `pidog.speak_block` → `sudo killall pulseaudio` (VNC workaround)
- `robot_hat.filedb.fileDB` → `sudo chmod`/`chown` on every `Robot()` init (3× per `Pidog()`)
- `robot_hat.utils.set_volume` → `sudo amixer` (not used by us)

Previously, with `sudo python3 ...` this went through (`os.geteuid()==0`). With `uv run` as user `dog` everything failed with `sudo: a terminal is required to read the password`.

**Fix:** monkey-patch in `aidog/hardware.py` → `_patch_sunfounder_sudo()`:
- `robot_hat.filedb.fileDB.file_check_create` → mode/owner are mapped to `None`
- `robot_hat.utils.run_command` → swallows every `sudo …` and also `play …` (see point 3)

### 2. PipeWire default sink routed incorrectly
The PipeWire default was `alsa_output.platform-fe00b840.mailbox.stereo-fallback` (HDMI/headphones mainboard) instead of `alsa_output.platform-soc_sound.stereo-fallback` (voicehat). Audio went to the wrong speaker → silence. Additionally, PipeWire volume was only at 40 %.

**Fix:** `aidog/hardware.py` → `_prepare_audio_routing()`:
- `pactl set-default-sink alsa_output.platform-soc_sound.stereo-fallback`
- `pactl set-sink-volume … 100%`
- `os.environ.setdefault("SDL_AUDIODRIVER", "pulse")` — without this variable pygame picks a default driver that bypasses our routing.

### 3. pygame.mixer.Sound hangs in the Pidog multithread context
`Pidog.speak_block` (internally → `pygame.mixer.Sound.play()`) reliably hangs in Pidog processes with active servo/sensor threads. Direct pygame without Pidog runs. Probably a lock conflict between the pygame mixer thread and one of the 16 Pidog threads. A hang cannot be killed with SIGKILL — it remains as a zombie and holds /dev/gpiochip0 → the next run fails with `lgpio.error: 'GPIO busy'`.

**Fix:** `aidog/skills/vocal.py` bypasses `dog.speak_block` entirely:
- `_play(name)` calls `subprocess.run(["paplay", path], check=False)` directly on the voicehat sink.
- The sound files were copied into the project's own `aidog/sounds/` directory (self-containment).
- Additionally, `_kill_stale_gpio_holders()` in `hardware.py` clears old hung Pidog processes before every new init.

### What remains open (cosmetic)
- `flow().run("howling"|"pant"|"lie"+snoring)` from `vocal.py` still calls Pidog's `preset_actions` — these internally use `dog.speak()`. In the first stress test (phase 6+) check whether this also hangs; if so, switch the presets to `_play` as well.
- `enable_speaker()` runs over lgpio during the Music init; we do not patch this away, because pin 12 is set correctly anyway (even after the DeprecationWarning).

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

## 13 · Phase 10 — Web UI (live view + intervention)

**Goal:** a browser UI on the Pi to watch what Buddy is currently doing, with the ability to intervene. LAN-only.

### 13.1 Architecture

- **Single process:** FastAPI + Uvicorn in the same asyncio event loop as the agent. Direct access to the hardware singleton, no IPC.
- **Prerequisite:** phase 6 must be done — the asyncio sensor event bus is extended into the general agent event bus.
- **Module:** `aidog/web/` with `server.py` (FastAPI app + routes) and `static/index.html` (vanilla JS, no build step).
- **CLI:** `uv run python main.py web` starts Uvicorn on port 8080, binds `0.0.0.0` (LAN-trusted, the Pi is behind the home firewall).
- **No auth.** README note: do not expose to the open internet. If needed later: HTTP basic auth or Tailscale.

### 13.2 Event bus (extended from phase 6)

The existing `asyncio.Queue` from § 5.7 becomes the general bus queue. New event types in addition to the sensor events:

| `kind` | Payload | When |
|---|---|---|
| `user_input` | `{source: "browser"\|"whisper", text: str}` | a user instruction comes in |
| `llm_request` | `{messages: [...], tools_count: int}` | LLM call begins |
| `llm_response` | `{tool_calls: [...], content: str\|null, usage: {...}}` | LLM response is in |
| `tool_call_start` | `{name: str, args: dict}` | tool execution begins |
| `tool_call_end` | `{name: str, result: any, duration_ms: int, error: str\|null}` | tool done |
| `state_change` | `{from: str, to: str}` | idle/listening/thinking/acting/error |
| `stop_requested` | `{kind: "soft"\|"hard"}` | user pressed stop |
| `config_change` | `{field: "openai_key", source: "browser"\|"env"}` | key was set |

The WebSocket multiplexes all events to connected browsers. Multi-client allowed (broadcast).

### 13.3 WebSocket protocol

**Server → client:** every event from 14.2 as JSON: `{kind, payload, ts}`.

**Client → server:**
```json
{"type": "user_message", "text": "Bell mal"}
{"type": "tool_call",    "name": "bark_once", "args": {}}
{"type": "stop_soft"}
{"type": "stop_hard"}
{"type": "set_openai_key", "key": "sk-...", "persist": true}
```

### 13.4 Stop implementation

Two `asyncio.Event`s (`_stop_soft`, `_stop_hard`) in the agent state:

- **Soft:** the tool loop checks `_stop_soft.is_set()` before each next tool call → break out of the loop. The current tool still finishes (clean servo position). The LLM gets a synthetic "stopped by user" message in the history.
- **Hard:** immediately `dog.body_stop()` (sync, blocking) + abort the tool task via `task.cancel()`. The dog stays in its current position. State → `error/interrupted`. LED → red.
- Both events are reset after acknowledgement by the next user action.

### 13.5 OpenAI key via UI (new)

**Source priority (highest first):**
1. Browser-entered key (in-memory in `LLMClient`, persisted only if `persist: true`)
2. `OPENAI_API_KEY` from `secrets.env`
3. `OPENAI_API_KEY` from the process env

**Behavior at startup:**
- The server checks at boot whether a key is present (sources 2–3). State: `key_status = "ok" | "missing"`.
- On `"missing"`: the agent runs in a "wait-for-key" mode — no LLM calls possible, all `user_input` events park in the queue. The UI shows a "OpenAI key missing" modal.
- On `"ok"`: normal operation, the UI shows the status small in the header.

**Persistence (`persist: true`):**
- The server writes an `OPENAI_API_KEY=...` line into `/home/dog/aidog/secrets.env`, replaces an existing line, keeps chmod 600.
- On `persist: false`: only in-memory until the server restarts.

**Validation before saving:**
- The server makes a cheap test call (`models.list()` or a mini completion with `max_tokens=1`).
- On error: response `{ok: false, error: "..."}`, the key is not adopted.

**Security:**
- LAN-only, no TLS — the key goes over the wire in plain text. Accepted for the home Wi-Fi; README note about it.
- The key is NEVER sent back in WebSocket events, only the status (`set | unset | invalid`).
- `secrets.env` chmod 600 is enforced on write.

### 13.5b Memory editor (CRUD over the web UI, feeds phase 11)

**WebSocket API extended:**
```json
{"type": "memory_list"}                                  // → server returns full list
{"type": "memory_add",  "text": "Pfötchen heißt rechte Pfote anheben"}
{"type": "memory_edit", "id": "...", "text": "..."}
{"type": "memory_delete", "id": "..."}
```

Server → client: `{"kind": "memory_changed", "payload": {"memories": [...]}}` as a broadcast after every change.

### 13.6 Frontend (single `index.html`, mobile-responsive)

**Mobile-responsive:** single-column layout with `viewport meta`, `flex-direction: column`, touch-friendly button heights (≥44 px), responsive font sizes (16 px base on mobile, scaled up on desktop). CSS variables for spacing, no framework. Direct tool buttons are collapsed into an accordion on mobile.

Four areas, one vertical layout (on desktop possibly two columns with memory on the right):

```
┌─────────────────────────────────────────────────┐
│ Buddy · State: thinking · Mood: curious · Akku  │  ← header (live)
│ OpenAI-Key: ✓ (env)                  [Settings] │
├─────────────────────────────────────────────────┤
│ [Soft Stop]  [HARD STOP]                        │  ← intervention bar
├─────────────────────────────────────────────────┤
│ 12:43:22 user>  Bell mal                        │
│ 12:43:22 llm→  request (5 tools, 3 history)    │  ← live log
│ 12:43:24 llm←  set_mood(happy), bark_once()    │     (auto-scroll,
│ 12:43:24 tool  set_mood(happy) ✓ 12ms          │      color-coded)
│ 12:43:25 tool  bark_once() ✓ 850ms             │
│ 12:43:25 llm→  request (continue)              │
│ 12:43:26 llm←  finish_reason=stop              │
├─────────────────────────────────────────────────┤
│ [Text-Input: "..."]                  [Senden]   │  ← user input
├─────────────────────────────────────────────────┤
│ Direkte Tool-Calls (Debug):                     │
│ Vocal:    [bark_once] [growl] [howl] ...        │  ← tool buttons,
│ Posture:  [sit] [stand] [lie_down] ...          │     categorized
│ ...                                             │     from the registry
├─────────────────────────────────────────────────┤
│ Erinnerungen (Tricks beibringen):               │  ← phase 11
│ [+] „Pfötchen = rechte Pfote heben"   [✏][🗑]   │
│ [+] „Sitz = sit + 2s warten + bark"   [✏][🗑]   │
│ [Neue Erinnerung…              ] [Hinzufügen]   │
└─────────────────────────────────────────────────┘
```

Tool buttons are generated at runtime from `aidog.skills.all_tools()` (the `/api/tools` endpoint). Tools with parameters get a small inline form.

Settings modal:
```
┌─ Settings ────────────────────┐
│ OpenAI API Key:               │
│ [sk-..........................]│
│ [✓] In secrets.env speichern  │
│ [Test & Speichern]  [Abbrechen]│
└───────────────────────────────┘
```

### 13.7 Dependencies

`uv add fastapi "uvicorn[standard]"` — `websockets` comes with `uvicorn[standard]`.

### 13.8 Success test

1. `uv run python main.py web` → Uvicorn runs on `:8080`, no crash.
2. Browser on `http://<pi-ip>:8080` shows the UI; without a key → "OpenAI key missing" modal.
3. Enter the key + "Test & Speichern" → modal closes, `secrets.env` contains the new line, chmod 600 preserved.
4. Send the text "Bell mal" → live log shows user_input, llm_request, llm_response with tool calls, tool_call_start/end for each tool. The dog barks.
5. During an action: **Soft Stop** → the running tool finishes, no new one; state → idle.
6. During movement: **Hard Stop** → the dog stops immediately; state → error/interrupted, LED red.
7. Direct tool click `bark_once` → the dog barks, no LLM entry in the log.
8. A second browser open in parallel → both see all events.

### 13.9 Risks

1. **Blocking calls in the event loop:** the OpenAI SDK + hardware calls are sync. Mitigation: pull all blocking calls out of the loop via `asyncio.to_thread(...)`. Without this, UI updates freeze during the LLM wait.
2. **Key leak via browser DevTools history:** clear the form field after entry. Do not include it in the WebSocket echo.
3. **Multi-client race on stop:** two browsers press at the same time → idempotent (setting the event is OK), but the UI state can briefly diverge. Accepted.
4. **`secrets.env` write race-free:** atomic via `tempfile + os.replace`, permissions set explicitly.
5. **WebSocket reconnect:** the browser loses the connection (Wi-Fi drop) → auto-reconnect with exponential backoff in the client; missed events are not redelivered (live log = best-effort, no history replay in the MVP).

---

---

## 13b · Phase 11 — Memory + RAG (teaching tricks)

**Goal:** Buddy learns tricks permanently. The user says "wenn ich ‚Pfötchen' sage, gib mir die rechte Pfote" → Buddy calls `remember(text)` → stores it in a file → on every later turn the memory is available.

### Storage

- **File:** `aidog/data/memories.json` (gitignored, editable by the user)
- **Format:**
  ```json
  [
    {"id": "uuid4", "text": "Pfötchen = rechte Pfote anheben",
     "created_at": "2026-05-15T16:30:00", "updated_at": "..."},
    ...
  ]
  ```
- Atomic write (tempfile + os.replace), file lock via `fcntl.flock` so web UI edits do not collide with dog writes.

### Tools (in `aidog/skills/memory.py`, new category `memory`)

| Tool | Parameters | Behavior |
|---|---|---|
| `remember` | `text: str` | append to memories.json, returns `{"id": ..., "count": N}` |
| `forget` | `id: str` (or `query: str` for the older variant) | remove from the file |

We do **not need `recall` as a tool**, because we automatically inject all memories into the system prompt (see below). Saves round-trips.

### Auto pre-inject into the system prompt

`LLMClient` loads the memories before every `run_turn` and injects them as an additional system message right after the main prompt:

```
[system] (SYSTEM_PROMPT aus prompt.py)
[system] Du erinnerst dich an folgende vom User beigebrachte Verhaltensweisen:
         - Pfötchen = rechte Pfote anheben
         - Wenn jemand „Buddy, schlafen!" sagt, leg dich hin und schnarche
         - Bei „Tanzen" wedeln + drehen + happy
[user]   ...
```

Pragmatic for ≤30 memories (~50 tokens per memory). For many more: switch to RAG later (embeddings + only top-K).

### Tool spec in the LLM prompt

Extend with:
- "Wenn der Mensch dir was Neues beibringen will (‚merk dir', ‚von jetzt an', ‚wenn ich X sage, mach Y'), ruf `remember(text)` mit einer prägnanten Beschreibung."
- "Du musst Erinnerungen NICHT explizit abrufen — die kommen automatisch in jeden Turn rein."

### Web UI integration (see § 13.5b)

CRUD over WebSocket: list/add/edit/delete. The server broadcasts `memory_changed` to all clients. On dog writes (via the `remember` tool) also broadcast → the web UI updates live.

### Success test

1. "hey buddy, merk dir: wenn ich Pfötchen sage, gib die rechte Pfote" → Buddy calls `remember(...)`. The web UI shows a new line.
2. New turn (even after a restart!): "hey buddy, Pfötchen" → Buddy raises a paw (because the system prompt contains the memory).
3. Web UI → delete the memory → the next "Pfötchen" turn ignores it.
4. Web UI → edit the memory manually ("gib die LINKE Pfote") → Buddy reacts changed.

### Risks

- **Prompt bloat:** with many memories the token consumption rises. Recommended limit: 50 entries of max 200 characters → ~10 K tokens system prompt overhead, still within range.
- **Conflict with the persona:** memories can contain contradictory instructions ("sei laut" vs. "sei leise"). The system prompt should clarify: on conflict the newer memory wins; hard persona rules (no speaking) are not overridable.
- **File lock race:** the dog writes + the user edits → fcntl.flock + atomic replace.
- **Backup:** `memories.json` is gitignored, the user should back it up themselves (or use the web UI export).

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
