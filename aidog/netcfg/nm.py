"""
Thin nmcli wrapper for the WiFi onboarding (phase 12).

All calls go through `nmcli`. On the target Pi `nmcli` works unprivileged for
status/scan; `hotspot`/`connect` may still need root via polkit — the
provisioning service is expected to run as root (see PLAN.md § 13).

nmcli's terminal mode (`-t`) escapes ':' and '\\' inside field values; we
un-escape when parsing. SSIDs with ':' are rare but handled.
"""
from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass

log = logging.getLogger(__name__)

HOTSPOT_CON_NAME = "ai-robo-dog-hotspot"


def _run(args: list[str], timeout: float = 20.0) -> tuple[int, str, str]:
    try:
        p = subprocess.run(["nmcli", *args], capture_output=True, text=True,
                            timeout=timeout)
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except FileNotFoundError:
        return 127, "", "nmcli not found"


def _unescape(s: str) -> str:
    out, i = [], 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            out.append(s[i + 1])
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _split_terminal(line: str) -> list[str]:
    """Split an nmcli -t line on unescaped ':'."""
    fields, cur, i = [], [], 0
    while i < len(line):
        c = line[i]
        if c == "\\" and i + 1 < len(line):
            cur.append(line[i + 1])
            i += 2
        elif c == ":":
            fields.append("".join(cur))
            cur = []
            i += 1
        else:
            cur.append(c)
            i += 1
    fields.append("".join(cur))
    return fields


@dataclass
class Network:
    ssid: str
    signal: int
    secured: bool
    in_use: bool


def connectivity() -> str:
    """'full' | 'limited' | 'portal' | 'none' | 'unknown'."""
    rc, out, _ = _run(["-t", "-f", "CONNECTIVITY", "general"], timeout=10)
    return out if rc == 0 and out else "unknown"


def is_online() -> bool:
    return connectivity() == "full"


def wifi_device() -> str | None:
    rc, out, _ = _run(["-t", "-f", "DEVICE,TYPE", "device"], timeout=10)
    if rc != 0:
        return None
    for line in out.splitlines():
        parts = _split_terminal(line)
        if len(parts) >= 2 and parts[1] == "wifi":
            return parts[0]
    return None


def active_wifi_profile() -> str | None:
    """The currently active wifi connection profile name (to restore later)."""
    rc, out, _ = _run(["-t", "-f", "NAME,TYPE", "connection", "show",
                        "--active"], timeout=10)
    if rc != 0:
        return None
    for line in out.splitlines():
        parts = _split_terminal(line)
        if len(parts) >= 2 and parts[1] == "802-11-wireless":
            return parts[0]
    return None


def scan(rescan: bool = False) -> list[Network]:
    args = ["-t", "-f", "SSID,SIGNAL,SECURITY,IN-USE", "device", "wifi",
            "list"]
    if rescan:
        args += ["--rescan", "yes"]
    rc, out, err = _run(args, timeout=30)
    if rc != 0:
        log.warning("wifi scan failed: %s", err)
        return []
    seen: dict[str, Network] = {}
    for line in out.splitlines():
        f = _split_terminal(line)
        if len(f) < 4:
            continue
        ssid = _unescape(f[0]).strip()
        if not ssid:
            continue
        try:
            signal = int(f[1])
        except ValueError:
            signal = 0
        secured = f[2].strip() not in ("", "--")
        in_use = f[3].strip() == "*"
        # Keep the strongest entry per SSID; in_use sticks if any BSSID has it.
        prev = seen.get(ssid)
        if prev is None:
            seen[ssid] = Network(ssid, signal, secured, in_use)
        else:
            seen[ssid] = Network(
                ssid,
                max(signal, prev.signal),
                secured or prev.secured,
                in_use or prev.in_use,
            )
    return sorted(seen.values(), key=lambda n: -n.signal)


def start_hotspot(ssid: str, password: str | None) -> tuple[bool, str]:
    """Bring up an AP. Empty/short password → open network."""
    dev = wifi_device() or "wlan0"
    args = ["device", "wifi", "hotspot", "ifname", dev,
            "con-name", HOTSPOT_CON_NAME, "ssid", ssid]
    if password and len(password) >= 8:
        args += ["password", password]
    rc, out, err = _run(args, timeout=25)
    if rc != 0:
        return False, err or out
    return True, ""


def stop_hotspot() -> None:
    _run(["connection", "down", HOTSPOT_CON_NAME], timeout=15)
    _run(["connection", "delete", HOTSPOT_CON_NAME], timeout=15)


def connect(ssid: str, psk: str | None) -> tuple[bool, str]:
    dev = wifi_device() or "wlan0"
    args = ["device", "wifi", "connect", ssid, "ifname", dev]
    if psk:
        args += ["password", psk]
    rc, out, err = _run(args, timeout=45)
    if rc != 0:
        return False, err or out
    return True, ""


def up_profile(name: str) -> bool:
    rc, _, _ = _run(["connection", "up", name], timeout=30)
    return rc == 0
