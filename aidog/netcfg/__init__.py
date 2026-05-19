"""
WiFi onboarding entry point (phase 12).

`provision()` is called before the aidog web UI starts. If already online it
returns immediately. Otherwise it raises the AP, runs the captive portal in a
thread, and blocks in the manager state machine until the dog is online.
"""
from __future__ import annotations

import logging
import threading

from .manager import Session, run as _run_manager

log = logging.getLogger(__name__)


def provision(*, ap_password: str | None = None, portal_port: int = 80) -> bool:
    """Returns True once online (normal startup may proceed)."""
    from . import nm
    if nm.is_online():
        log.info("netcfg: online — skipping onboarding")
        return True

    session = Session()

    def _portal() -> None:
        try:
            from .portal.server import serve
            serve(session, host="0.0.0.0", port=portal_port)
        except Exception as exc:
            log.error("netcfg portal crashed: %s", exc)

    t = threading.Thread(target=_portal, name="netcfg-portal", daemon=True)
    t.start()
    return _run_manager(session, ap_password=ap_password)
