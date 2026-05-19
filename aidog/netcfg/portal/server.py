"""
Captive portal for WiFi onboarding (phase 12).

A tiny FastAPI app served on port 80 while the AP is up. The OS captive-
portal probes (Apple/Android/Windows) get a 302 to `/` so the login sheet
pops automatically; everything else also redirects to `/` as a fallback for
DNS hijack. Network list + connect requests go through the shared `Session`.
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from ... import i18n
from ..manager import Session

log = logging.getLogger(__name__)

_INDEX = Path(__file__).resolve().parent / "static" / "index.html"

# OS connectivity-check endpoints. Returning a redirect instead of the
# expected body is what makes the captive-portal sheet appear.
_PROBE_PATHS = {
    "/generate_204", "/gen_204",                       # Android
    "/hotspot-detect.html",                            # Apple
    "/library/test/success.html",                      # Apple
    "/ncsi.txt", "/connecttest.txt",                   # Windows
    "/redirect", "/canonical.html", "/success.txt",
}


def build_app(session: Session) -> FastAPI:
    app = FastAPI(title="ai-robo-dog onboarding")

    @app.get("/", response_class=HTMLResponse)
    async def index() -> HTMLResponse:
        return HTMLResponse(_INDEX.read_text())

    @app.get("/api/i18n")
    async def api_i18n(lang: str | None = None) -> JSONResponse:
        # Onboarding may need a language switch before config is trusted.
        use = lang if lang in ("de", "en") else i18n.lang()
        merged = dict(i18n._STRINGS["en"])
        merged.update(i18n._STRINGS.get(use, {}))
        strings = {k: v for k, v in merged.items() if k.startswith("np.")}
        return JSONResponse({"lang": use, "strings": strings})

    @app.get("/api/state")
    async def api_state() -> JSONResponse:
        return JSONResponse(session.snapshot())

    @app.post("/api/connect")
    async def api_connect(req: Request) -> JSONResponse:
        body = await req.json()
        ssid = (body.get("ssid") or "").strip()
        psk = body.get("psk") or ""
        if not ssid:
            return JSONResponse({"ok": False, "error": "np.no_ssid"},
                                status_code=400)
        session.request_connect(ssid, psk)
        return JSONResponse({"ok": True})

    @app.post("/api/rescan")
    async def api_rescan() -> JSONResponse:
        session.request_rescan()
        return JSONResponse({"ok": True})

    @app.get("/{path:path}")
    async def catch_all(path: str, request: Request):
        # Captive probes + DNS-hijack fallback → bounce to the portal page.
        return RedirectResponse(url="/", status_code=302)

    return app


def serve(session: Session, host: str = "0.0.0.0", port: int = 80) -> None:
    import uvicorn
    uvicorn.run(build_app(session), host=host, port=port, log_level="warning")
