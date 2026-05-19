# AGENTS.md

Conventions and context for AI coding assistants working in this repo. Anyone
who jumps in without reading this file is very likely to build something that
goes wrong on the hardware or cuts across the plan.

## What this repo is

`Ai-Robo-Dog` = an LLM agent for the SunFounder PiDog v2. The goal is a robot
dog that reacts like a real dog: dog sounds, body language, LED mood. **No**
text/speech output. The LLM "speaks" exclusively through tool calls.

The master plan is [PLAN.md](PLAN.md). Before changing code, check the phase
table — we work phase by phase and skip none.

## Hardware reality — please read

- **Real servos.** Every CLI `call` drives 12 servos. If the dog is not
  standing or lying safely, it can fall or run into furniture.
- `pidog.Pidog()` already moves the legs into a calibration position in its
  constructor. You cannot instantiate it "quietly".
- `Pidog.close()` runs `stop_and_lie()` — that is the correct shutdown
  sequence. `aidog.hardware` registers it via `atexit`, so never call
  `os._exit` or similar yourself.
- **Never** edit anything in `/home/dog/pidog/`, `/home/dog/vilib/` or
  `/home/dog/robot-hat/`. Those are SunFounder sources for reference. The
  installed packages live in `/usr/local/lib/python3.13/dist-packages/` and
  come from the vendor installer.

## Package manager: uv, exclusively

- Never `pip install` directly. Always `uv add <dep>` (writes to
  `pyproject.toml` and `uv.lock`) or `uv sync` (reproduces from the lock).
- The venv is created with `--system-site-packages` so that `pidog`/`vilib`/
  `robot_hat` from the system are visible. Do **not** add these libs to
  `dependencies` — the system installation is the single source of truth.
- `[tool.uv] python-preference = "only-system"` — uv must not download its own
  Python, because it would be missing the hardware bindings.
- Run everything with `uv run python ...`, never with `python3` without venv
  activation.

## Code style

- **No comments** except where the *why* is not in the code (hardware quirk,
  non-obvious invariant, workaround). Never describe *what* the code does —
  good names are enough.
- **No docstrings** for trivial functions. Only module docstrings where they
  give context that does not follow from the code (see `aidog/hardware.py`,
  `aidog/led/controller.py`).
- **No defensive programming** in internal modules. Trust internal code.
  Validate only at system boundaries (user input, external APIs).
- **No premature abstractions.** Three similar lines beat one `Factory`.
  Introduce classes only when state belongs together.
- **No backwards-compat hacks.** If something is dead, delete it. We are
  pre-1.0.
- **The Pidog API is the spec**, not inspiration: `dog.do_action(...)`,
  `flow.run(...)`, `dog.speak(...)`, `dog.rgb_strip.set_mode(...)` are used
  directly. No custom wrappers that hide more than necessary.

## Tool registry

Skills are registered via the `@tool(name, description, category=...)`
decorator in `aidog/skills/registry.py`. The decorator reads type hints and
`Literal[...]` args automatically — the later JSON schema for OpenAI
function-calling derives from that.

Rules for new skills:

- One function = one tool. No "mega-tool" with a `mode` parameter.
- Tool name in snake_case, descriptive (`bark_once`, not `b1`).
- Description in one sentence, written from the *dog's perspective* (the LLM
  reads it).
- Parameter types with default values — the decorator generates the LLM-schema
  required markers from those.
- `Literal["a","b"]` for enum-like parameters, *not* `str`.
- Nothing in `__init__.py` except importing the skill modules (that triggers
  registration).

## Configuration

`config.yaml` *already* contains the settings for all phases — Wake/STT/LLM/
sensor blocks are ignored as long as the modules are missing. **Do not remove
these settings.** If you change something, update the loader in
`aidog/config.py` at the same time.

`secrets.env` is gitignored and chmod 600. Put nothing in it but API keys.
`secrets.env.example` shows the expected format.

## Testing

There are (still) **no unit tests** and no CI. The test strategy is:

1. Dry run: `uv run python -c "from aidog import skills; print(len(skills.all_tools()))"`
   — must print 37+ without import errors.
2. CLI listing: `uv run python main.py list` — no exception.
3. Hardware smoke: individual tool calls via the CLI, watch what the
   servos/LED do. **Manual, supervised.**

Before claiming something works: run at least 1 and 2 yourself. Step 3 is done
by the user — don't ask "should I test", give them the exact commands.

## What you should *not* do

- **Skip phases.** Phase 5 (sensors) depends on phase 2 (LLM) being in place.
  If the LLM setup bores you, don't secretly slip in sensors.
- **Modify the `pidog` repo.** That is SunFounder code; changes disappear on
  the next installer run and break the hardware.
- **Force `asyncio`** where the code is still synchronous. Phase 6 brings
  asyncio officially — until then it stays synchronous.
- **Change system packages via pip.** `pip3 install ...` without a venv
  crashes due to PEP 668; that is intentional, not a problem to work around
  with `--break-system-packages`.
- **Let README/AGENTS/PLAN/BUILD_LOG diverge in parallel.** When the plan
  changes, keep them in sync. PLAN.md = architecture + open work; BUILD_LOG.md
  = history of completed phases; README = user-facing; AGENTS = these
  conventions. These are the only doc files we deliberately maintain.

## Phase workflow

When the user says "do phase X":

1. Find the phase in the PLAN, read its content + success test.
2. If the phase changes hardware behavior (movement, sound), explicitly ask
   whether the hardware is ready *before* you trigger tool calls.
3. Finish the phase, then: set its status to ✅ in the PLAN.md phase table,
   and add a short "What was built in phase X" note to **BUILD_LOG.md** (not
   PLAN.md — PLAN.md holds only architecture reference + open planning, the
   build history lives in BUILD_LOG.md). Don't document every bugfix — only
   the completed phases.
4. Update the README when new CLI commands or setup steps are added.

## When in doubt

Ask the user. Especially for: a new hardware action, a new external API, a
change to the `pyproject.toml`/`config.yaml` schema, file renames. Three lines
of clarification save a day of rework.
