# Security Policy

This is a small hobby project — no security team, no SLAs. That said: if you
find something that could harm users, please tell me.

## Supported versions

Only `main` is supported. There are no releases or LTS branches.

## Reporting a vulnerability

Please **do not** open a public issue for security problems. Instead:

- Email **marcel.duetscher@gmail.com**, or
- Use GitHub's
  [private vulnerability reporting](https://github.com/marceld23/Ai-Robo-Dog/security/advisories/new).

Include a short reproduction and the impact you see. I'll respond as soon as
I can — usually within a few days.

## Scope

In scope: code in this repository (`aidog/`, `main.py`, `start.sh`, the
systemd units in `deploy/`, the captive-portal in `aidog/netcfg/`).

Out of scope: the SunFounder vendor libraries (`pidog`, `vilib`, `robot_hat`)
— report those upstream at <https://github.com/sunfounder>. The Pi OS,
NetworkManager, PipeWire and other system components are also out of scope.
