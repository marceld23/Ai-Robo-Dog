"""
WiFi onboarding state machine (phase 12).

CHECK → (online? done) → SCAN → AP-UP → PORTAL → wait for the user → CONNECT
→ verify → (ok? done : back to AP-UP).

The portal FastAPI app runs in a uvicorn thread and shares a `Session`
object with this manager: the portal writes a connect request, the manager
loop performs the privileged nmcli work and reports the result back.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

from . import nm

log = logging.getLogger(__name__)

CHECK_TIMEOUT_SEC = 45.0
CONNECT_VERIFY_TIMEOUT_SEC = 35.0
AP_SSID = "ai-robo-dog-wifi"


@dataclass
class Session:
    """Shared state between the manager loop and the portal server."""
    networks: list[dict] = field(default_factory=list)
    status: str = "starting"          # starting|portal|connecting|online|error
    message: str = ""                 # localized-key hint for the UI
    online_ip: str = ""
    _connect_req: tuple[str, str] | None = None
    _rescan_req: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock)

    # --- portal-side API ---
    def request_connect(self, ssid: str, psk: str) -> None:
        with self._lock:
            self._connect_req = (ssid, psk)
            self.status = "connecting"
            self.message = "np.connecting"

    def request_rescan(self) -> None:
        with self._lock:
            self._rescan_req = True

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "status": self.status,
                "message": self.message,
                "online_ip": self.online_ip,
                "networks": list(self.networks),
            }

    # --- manager-side API ---
    def _take_connect(self) -> tuple[str, str] | None:
        with self._lock:
            r, self._connect_req = self._connect_req, None
            return r

    def _take_rescan(self) -> bool:
        with self._lock:
            r, self._rescan_req = self._rescan_req, False
            return r

    def _set(self, status: str, message: str = "") -> None:
        with self._lock:
            self.status = status
            self.message = message


def _scan_into(session: Session, rescan: bool = False) -> None:
    nets = nm.scan(rescan=rescan)
    with session._lock:
        session.networks = [
            {"ssid": n.ssid, "signal": n.signal, "secured": n.secured,
             "in_use": n.in_use}
            for n in nets
        ]


def _wait_online(timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if nm.is_online():
            return True
        time.sleep(2.0)
    return False


def _primary_ip() -> str:
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return ""


def run(session: Session, *, ap_password: str | None = None) -> bool:
    """Blocking onboarding loop. Returns True when online (normal aidog
    startup may proceed), never returns while stuck in the portal."""
    # 1. CHECK — NetworkManager auto-connects known networks on boot.
    log.info("netcfg: waiting up to %ss for a known network...", CHECK_TIMEOUT_SEC)
    if _wait_online(CHECK_TIMEOUT_SEC):
        log.info("netcfg: already online — no onboarding needed")
        return True

    saved_profile = nm.active_wifi_profile()
    log.warning("netcfg: no WiFi — starting onboarding AP %r", AP_SSID)

    # 2. SCAN before raising the AP (single radio: cannot scan with AP up).
    _scan_into(session)
    log.info("netcfg: cached %d networks", len(session.networks))

    while True:
        # 3. AP-UP
        ok, err = nm.start_hotspot(AP_SSID, ap_password)
        if not ok:
            log.error("netcfg: hotspot failed: %s — retrying in 10s", err)
            session._set("error", "np.ap_failed")
            time.sleep(10)
            continue
        session._set("portal", "np.pick_network")
        log.info("netcfg: AP up, portal active")

        # 4./5. WAIT for a connect request from the portal
        while True:
            if session._take_rescan():
                nm.stop_hotspot()
                _scan_into(session, rescan=True)
                ok, err = nm.start_hotspot(AP_SSID, ap_password)
                if not ok:
                    session._set("error", "np.ap_failed")
                    break
                session._set("portal", "np.pick_network")
            req = session._take_connect()
            if req is not None:
                break
            time.sleep(0.5)
        if req is None:
            continue  # rescan re-raise failed, loop AP-UP again

        ssid, psk = req
        log.info("netcfg: connect request for %r", ssid)
        session._set("connecting", "np.connecting")

        # 6. CONNECT — drop AP, try to join, verify connectivity.
        nm.stop_hotspot()
        cok, cerr = nm.connect(ssid, psk)
        if cok and _wait_online(CONNECT_VERIFY_TIMEOUT_SEC):
            ip = _primary_ip()
            with session._lock:
                session.status = "online"
                session.message = "np.online"
                session.online_ip = ip
            log.info("netcfg: connected to %r, online at %s", ssid, ip)
            time.sleep(4.0)  # let the portal show the success screen
            return True

        # Failure: restore the old known profile if possible, re-raise AP.
        log.warning("netcfg: connect to %r failed (%s)", ssid, cerr or "no connectivity")
        if saved_profile:
            nm.up_profile(saved_profile)
            if _wait_online(8.0):
                ip = _primary_ip()
                with session._lock:
                    session.status = "online"
                    session.online_ip = ip
                return True
        session._set("error", "np.connect_failed")
