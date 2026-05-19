# Ai-Robo-Dog

LLM-driven dog on a SunFounder PiDog v2 (Raspberry Pi 4). The dog never speaks
words — it barks, growls, howls, moves, and shows its mood via the chest LED
strip. Driven by an LLM through tool-calling.

Hardware & SunFounder docs: <https://docs.sunfounder.com/projects/pidog/en/latest/>

**Status:** Phases 0–12 done (skeleton, 45 skills, function-calling, Whisper STT,
wake-word, vision with gpt-5.4-mini, sensor bus with touch + ultrasonic +
sound-direction + battery, LED lifecycle incl. pause, critical shutdown, memory
for teaching tricks, **Web UI with live telemetry, camera, memory editor, pause
toggle, voice-stop**, **WiFi onboarding captive portal**, bilingual DE/EN).
Remaining: phase 8 (personality tuning, ongoing) and phase 9 (robustness /
30-min stress test).

Open plan & architecture: [PLAN.md](PLAN.md) · How completed phases were built:
[BUILD_LOG.md](BUILD_LOG.md) · Conventions for AI assistants: [AGENTS.md](AGENTS.md)

## Prerequisite: SunFounder hardware bring-up (one-time, before this project)

This repo contains only the LLM agent. The PiDog hardware libraries are
SunFounder's (GPLv3) and must be installed separately first. Canonical guide:
<https://docs.sunfounder.com/projects/pidog/en/latest/python/python_start/install_all_modules.html>

The steps below reconstruct how this device was set up (Raspberry Pi OS /
Debian, Python 3.13). Install **in this order** — `robot-hat` is the base
layer, `pidog` depends on it. Each installs system-wide.

```bash
# 1. robot-hat (base hardware library)
cd ~ && git clone https://github.com/sunfounder/robot-hat.git
cd robot-hat && sudo python3 install.py

# 2. vilib (camera / vision)
cd ~ && git clone https://github.com/sunfounder/vilib.git
cd vilib && sudo python3 install.py

# 3. pidog (the dog itself)
cd ~ && git clone https://github.com/sunfounder/pidog.git
cd pidog && sudo python3 setup.py install   # pidog has no install.py; pyproject/setup install

# 4. I2S speaker + mic (the voicehat audio HAT)
sudo bash ~/pidog/i2samp.sh                  # answer yes to the prompts

# 5. reboot so the dtoverlay/soundcard comes up
sudo reboot
```

Verified versions on this device: `robot_hat 2.5.2a1`, `vilib 0.3.18`,
`pidog 1.3.13`. The three repos stay in `~/` as reference sources (do not
edit them — see [AGENTS.md](AGENTS.md)); the importable packages live under
`/usr/local/lib/python3.13/dist-packages/`.

### Calibrate the dog (one-time, after assembly)

The legs/head/tail servos have mechanical offsets that must be trimmed once.
Stand the dog safely (it will move), then:

```bash
sudo python3 ~/pidog/examples/0_calibration.py
```

Follow the on-screen prompts to zero each servo; saving writes the offsets to
`~/.config/pidog/pidog.conf` (e.g. `legs_servo_offset_list = [...]`). This
project reads that file via the SunFounder libs — no calibration data lives
in this repo. Re-run calibration if you re-assemble or a servo slips.

## Setup

Requirements: PiDog v2 with the SunFounder bring-up above completed (`pidog`,
`vilib`, `robot_hat` installed system-wide under
`/usr/local/lib/python3.13/dist-packages/`), Python 3.13,
[uv](https://docs.astral.sh/uv/).

```bash
cd /home/dog/Ai-Robo-Dog

# venv with access to the system hardware libs
uv venv --python /usr/bin/python3 --system-site-packages

# install dependencies
uv sync

# set up the OpenAI key (phase 2+)
cp secrets.env.example secrets.env
chmod 600 secrets.env
# content of secrets.env: OPENAI_API_KEY=sk-...
```

The dog sound files are SunFounder assets (GPLv3) and are **not** included in
this repository. `start.sh` copies them automatically from `~/pidog/sounds` on
first run. To do it manually:

```bash
mkdir -p aidog/sounds
cp ~/pidog/sounds/*.mp3 ~/pidog/sounds/*.wav aidog/sounds/
```

### Language & wake-word model

The project is localized in **German and English**. Set the language once in
`config.yaml`:

```yaml
language: de   # or: en
```

This drives the UI strings, the system prompt, the Whisper STT language, the
voice "stop" phrases, and which Vosk wake-word model is used. Download the
model for your language into `models/`:

```bash
mkdir -p models && cd models
# German (default):
curl -L https://alphacephei.com/vosk/models/vosk-model-small-de-0.15.zip -o de.zip && unzip de.zip && rm de.zip
# English:
curl -L https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip -o en.zip && unzip en.zip && rm en.zip
cd ..
```

`models/` is gitignored. The wake phrase (`hey buddy`) works in both models.

### Disable Pi-4 WiFi power-save (important)

Without this the SSH connection drops during longer Web-UI runs (known
brcmfmac bug with power-save under CPU load). One-time:

```bash
sudo iw wlan0 set power_save off
sudo bash -c 'echo "[connection]
wifi.powersave = 2" > /etc/NetworkManager/conf.d/99-disable-wifi-powersave.conf'
```

Persistent across reboots thanks to the NetworkManager file. Verify with
`iw wlan0 get power_save` (should read "off").

## CLI

```bash
# list every registered tool
uv run python main.py list

# describe a single tool
uv run python main.py describe set_mood

# call a tool
uv run python main.py call set_mood mood=happy
uv run python main.py call wag_tail intensity=2
uv run python main.py call sit

# call several tools in a row
uv run python main.py sequence stand wag_tail bark_once

# chat with the dog (phase 2, needs OPENAI_API_KEY in secrets.env)
uv run python main.py chat
uv run python main.py chat --say "Hey Buddy, bark!"

# voice + sensor loop (phase 4–7a, needs OPENAI_API_KEY)
uv run python main.py listen
# triggers: say "hey buddy …" OR stroke the head OR hold a hand in front of the snout
# every voice command automatically attaches a camera image
# LED status: white-breath=idle · cyan-flash=wake · GREEN=speak now
#             yellow=Whisper/LLM running · LLM-mood=dog reaction · red=error
#             magenta-breath=paused (Web UI)
# head pose: left=Whisper · right=LLM · neutral=ready
```

### Web UI (recommended way to run, phase 10)

```bash
./start.sh                 # foreground, Ctrl+C to quit
./start.sh --background    # nohup, logs to /tmp/aidog.log
PORT=9000 ./start.sh       # different port
```

UI at `http://<pi-ip>:8080`. Mobile-responsive. Provides:

- **Live camera image** (every 2 s, pausable)
- **Sensors panel**: distance, battery voltage + zone + %, pitch/roll, LED
  state, **sound compass** with direction + age
- **Live log** with green highlight for `llm_input` events (what the dog is
  currently sending to the LLM, incl. telemetry snapshot)
- **Input field** for direct text to Buddy (alternative to voice)
- **STOP**: `body_stop` + neutral stand pose + LLM-loop abort
- **Pause / Resume**: sensors keep running, but no LLM call. LED breathes
  magenta. Saying "**Stop**" / "**Aus**" / "**Halt**" goes straight to a
  neutral pose without the LLM.
- **Memories**: view, add, edit, delete — Buddy learns tricks permanently
- **Direct tool calls** (debug): all 45 tools as buttons from the registry
- **Settings ⚙️**: enter the OpenAI key, optionally persist it to `secrets.env`

**Safety note:** every `call`/`sequence` invocation initializes the real
hardware. The `Pidog()` constructor drives the servos to a calibrated start
position — the dog must be standing safely and stably beforehand.

## Running the dog — TL;DR

1. Make sure the dog stands safely (servos move on start).
2. `cd /home/dog/Ai-Robo-Dog && ./start.sh --background`
3. Open `http://<pi-ip>:8080` on your phone/laptop.
4. If you started paused (recommended), click **Resume** in the Web UI —
   only then does Buddy talk to the LLM.
5. Stop it: `pkill -f 'main.py web'` (or `kill <PID>` shown by start.sh).

```bash
./start.sh --background          # normal, active immediately
PAUSED=1 ./start.sh --background # boot inert, act only after Web UI "Resume"
```

## WiFi onboarding (phase 12)

If the dog finds no known WiFi within ~45 s of boot, it opens its own
access point **`ai-robo-dog-wifi`** with a captive portal (DE/EN). Connect a
phone to it, the setup page pops up automatically (or open
`http://192.168.4.1`), pick your network, enter the password — the dog joins
it and the normal Web UI becomes reachable at the new IP.

Manual run (needs root for the AP + port 80):

```bash
sudo /home/dog/.local/bin/uv run python main.py netcfg --ap-password robodogsetup
```

## Autostart on boot (systemd)

Two units in [`deploy/`](deploy/): `ai-robo-dog-netcfg.service` (root, runs
the WiFi onboarding first) and `ai-robo-dog.service` (the dog user, starts
the Web UI **paused** so it boots inert and only acts after you click
*Resume*).

```bash
# One-time: keep the dog user's PipeWire session alive from boot, so the
# system service can reach audio (otherwise: pa_context_connect refused →
# no sound). The unit points PULSE_SERVER/XDG_RUNTIME_DIR at /run/user/1000.
sudo loginctl enable-linger dog

sudo cp deploy/ai-robo-dog-netcfg.service deploy/ai-robo-dog.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ai-robo-dog-netcfg.service ai-robo-dog.service
journalctl -u ai-robo-dog -f      # follow logs
```

After a reboot the dog comes up online and **paused** — open the Web UI and
press **Resume** to let it react. Edit the units if your paths differ
(`uv` location, working directory, AP password, or the runtime-dir uid if the
service user isn't uid 1000).

## Configuration

All parameters live in [config.yaml](config.yaml). It already contains settings
for later phases (wake-word, STT, LLM, sensors) — they are ignored as long as
the corresponding modules are not implemented.

`secrets.env` is gitignored and chmod'ed to `0600`.

## Project structure (short form)

```
Ai-Robo-Dog/
├── main.py           # CLI
├── config.yaml
├── secrets.env       # gitignored
├── PLAN.md           # architecture + open plan (phases 8, 9, 12)
├── BUILD_LOG.md      # how the completed phases were built
├── AGENTS.md         # for AI assistants
└── aidog/
    ├── hardware.py   # Pidog/ActionFlow singleton
    ├── config.py
    ├── log.py
    ├── led/          # LedController + mood
    ├── skills/       # @tool registry + tools
    ├── audio/        # recorder, STT, wake-word
    ├── sensors/      # threading event bus + sensors
    ├── memory/       # JSON persistent memories
    └── web/          # FastAPI + WebSocket UI
```

Full layout tree: see [PLAN.md § 4](PLAN.md).

## License

This repository's source code is licensed under the [MIT License](LICENSE).

The MIT license covers **only** the code in this repo. At runtime the project
imports the SunFounder hardware libraries `pidog`, `vilib`, `robot_hat`, which
are **GPLv3** and installed separately by SunFounder's own installer — they are
not bundled or redistributed here. Declared Python dependencies are all under
permissive licenses (MIT / BSD-3 / Apache-2.0). See the [LICENSE](LICENSE) file
for the full third-party breakdown.
