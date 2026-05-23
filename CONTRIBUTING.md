# Contributing

Ai-Robo-Dog is a small hobby project, but PRs and ideas are welcome.

## Before you start

- Open an [issue](https://github.com/marceld23/Ai-Robo-Dog/issues) first if
  you're planning a non-trivial change — saves both of us time if the idea
  doesn't fit.
- Read [AGENTS.md](AGENTS.md) — it documents the hardware reality, the
  package-manager rules (`uv` only) and the code style we use. It's written
  for AI assistants but is just as useful for humans.
- The architecture is in [ARCHITECTURE.md](ARCHITECTURE.md); the open work in
  [PLAN.md](PLAN.md).

## Setup

The full bring-up (SunFounder hardware libs, uv venv, secrets, models) is in
[README.md](README.md#prerequisite-sunfounder-hardware-bring-up-one-time-before-this-project).
You need a real PiDog v2 to test anything touching hardware.

## Pull requests

- Small, focused PRs. One concern per PR.
- Match the existing code style — no comments unless the *why* isn't in the
  code, no premature abstractions, no defensive programming inside the project.
- If you change CLI commands or setup steps, update the README.
- If you finish an item from PLAN.md, remove it from PLAN.md and fold the
  resulting design into ARCHITECTURE.md.
- There is no CI and no test suite yet — please describe how you verified your
  change in the PR description (CLI dry-run, hardware smoke test, etc.).

## Bug reports

Please include: what you ran, what you expected, what happened, any relevant
log output (`journalctl -u ai-robo-dog -n 200` or `/tmp/aidog.log`), and your
hardware/OS versions.
