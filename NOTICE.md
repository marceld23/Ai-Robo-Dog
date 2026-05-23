# Third-party components

The [MIT License](LICENSE) covers **only** the source code in this repository.
This project does not bundle or redistribute third-party code; the libraries
below are installed separately at setup time.

## Runtime hardware libraries (GPLv3, installed by the SunFounder installer)

- [pidog](https://github.com/sunfounder/pidog) — SunFounder, GPLv3
- [vilib](https://github.com/sunfounder/vilib) — SunFounder, GPLv3
- [robot-hat](https://github.com/sunfounder/robot-hat) — SunFounder, GPLv3

These libraries are **not** part of this repository, **not** listed in
`pyproject.toml`, and must be obtained from SunFounder. If you redistribute a
combined / installed system that includes them, the combined work as
distributed may be subject to the terms of the GPLv3 for those components. The
code in this repository on its own remains under MIT.

## Declared Python dependencies (permissive, MIT-compatible)

- PyYAML — MIT
- python-dotenv — BSD-3-Clause
- openai — Apache-2.0
- webrtcvad — MIT
- vosk — Apache-2.0
- fastapi — MIT
- uvicorn — BSD-3-Clause

## Models and assets downloaded at setup time

- Vosk speech models (`vosk-model-small-de-0.15`,
  `vosk-model-small-en-us-0.15`) — Apache-2.0, Alpha Cephei. Not included in
  the repository.
- Dog sound files (`aidog/sounds/*.wav` / `*.mp3`) — SunFounder assets, GPLv3.
  Not included in the repository; copied at first run from `~/pidog/sounds/`.
