"""
Singleton access to the physical PiDog and its ActionFlow.

The real Pidog() spins up legs/head/tail/imu/rgb/sensor threads in __init__
and must be closed via .close() to land safely. We hand out one instance and
register an atexit hook so any CLI path leaves the dog in a defined posture.
"""
from __future__ import annotations

import atexit
import logging
import os
import shutil
import subprocess
import threading
import time
from typing import Any

log = logging.getLogger(__name__)

_dog = None
_flow = None
_camera_started = False
_lock = threading.Lock()
_startup_wait_sec = 1.0

# Camera freeze detection: a frontend timeout leaves the last frame stuck in
# Vilib.img (not None), so the None-check never fires and the UI shows a
# frozen still forever. Track a cheap frame fingerprint + the last time we
# saw a genuinely new frame.
_cam_last_sig: int | None = None
_cam_frozen_count = 0
_cam_last_fresh = 0.0
_CAM_FREEZE_LIMIT = 4  # identical frames in a row → force a camera restart
_patched = False
_audio_prepared = False
_voicehat_sink = "alsa_output.platform-soc_sound.stereo-fallback"


def configure(cfg: dict[str, Any] | None = None) -> None:
    global _startup_wait_sec
    cfg = cfg or {}
    _startup_wait_sec = float(cfg.get("startup_wait_sec", 1.0))


def _patch_sunfounder_sudo() -> None:
    """SunFounder's pidog/robot_hat blindly call `sudo …` internally — which
    fails as an unprivileged user. We patch the two spots that affect us:

    - `robot_hat.filedb.fileDB.file_check_create` unconditionally runs `sudo
      chmod`/`sudo chown` even when the config file is already in place
      correctly. We ignore mode/owner — the file is created by us on the first
      run and keeps its permissions.
    - `Pidog.speak`/`speak_block` tries `sudo killall pulseaudio` (a VNC
      workaround) and then falls back to `dog.music.sound_play(...)`.
      We cut the sudo call, the rest works unchanged.
    """
    global _patched
    if _patched:
        return

    from robot_hat import filedb
    _orig_file_check_create = filedb.fileDB.file_check_create

    def _file_check_create(self, file_path, mode=None, owner=None):
        return _orig_file_check_create(self, file_path, None, None)

    filedb.fileDB.file_check_create = _file_check_create

    from robot_hat import utils as rh_utils
    _orig_run_command = rh_utils.run_command

    def _run_command(cmd, user=None, group=None):
        if isinstance(cmd, str):
            if cmd.startswith("sudo "):
                return 0, ""
            if cmd.startswith("play "):
                return 0, ""
        return _orig_run_command(cmd, user=user, group=group)

    rh_utils.run_command = _run_command

    # robot_hat.device.get_battery_voltage() references `global _adc_obj`,
    # which is never initialized at module level → NameError on the first
    # call. We initialize it as None, then the `isinstance` check passes
    # cleanly and creates the ADC object lazily.
    from robot_hat import device as rh_device
    if not hasattr(rh_device, "_adc_obj"):
        rh_device._adc_obj = None

    _patched = True


def _kill_stale_gpio_holders() -> None:
    """Earlier Pidog processes sometimes hang in the speak block (pygame.mixer
    deadlock on the voicehat ALSA device) and are not cleaned up properly even
    by SIGKILL — they keep /dev/gpiochip0 claimed. On the next start `Pin('D0')`
    then fails with `lgpio.error: 'GPIO busy'`. We look for foreign Python
    processes with an open gpiochip0 handle and kill them.
    """
    my_pid = os.getpid()
    holders: list[int] = []
    try:
        for entry in os.scandir("/proc"):
            if not entry.name.isdigit():
                continue
            pid = int(entry.name)
            if pid == my_pid:
                continue
            fd_dir = f"/proc/{pid}/fd"
            try:
                for fd in os.scandir(fd_dir):
                    target = os.readlink(fd.path)
                    if target.startswith("/dev/gpiochip"):
                        holders.append(pid)
                        break
            except (FileNotFoundError, PermissionError):
                continue
    except Exception as exc:
        log.warning("gpio holder scan failed: %s", exc)
        return
    for pid in holders:
        try:
            cmdline = open(f"/proc/{pid}/cmdline").read().replace("\0", " ")[:80]
        except Exception:
            cmdline = "?"
        log.warning("killing stale gpio holder pid=%d cmd=%s", pid, cmdline)
        try:
            os.kill(pid, 9)
        except ProcessLookupError:
            pass
    if holders:
        time.sleep(0.5)


def _prepare_audio_routing() -> None:
    """The PipeWire default sink is set by default to the mainboard audio
    output (HDMI/headphones), not the voicehat. Without switching it pygame
    plays into the wrong speaker and nothing comes out. We set the voicehat as
    the default sink and turn it up to 100 % — per process start, no system
    config change.
    """
    global _audio_prepared
    if _audio_prepared:
        return
    os.environ.setdefault("SDL_AUDIODRIVER", "pulse")
    if shutil.which("pactl") is None:
        log.warning("pactl not found — skipping audio routing setup")
        _audio_prepared = True
        return
    for args in (
        ["pactl", "set-default-sink", _voicehat_sink],
        ["pactl", "set-sink-volume", _voicehat_sink, "100%"],
        # GPIO20 is PCM_DIN (mic input). Some Pidog init paths leave it as a
        # plain input → mic delivers silence. Force it back to Alt0.
        ["pinctrl", "set", "20", "a0"],
    ):
        result = subprocess.run(args, capture_output=True, text=True)
        if result.returncode != 0:
            log.warning("audio prep %s failed: %s", args[1], result.stderr.strip())
    _audio_prepared = True


def dog():
    global _dog
    if _dog is not None:
        return _dog
    with _lock:
        if _dog is not None:
            return _dog
        _patch_sunfounder_sudo()
        _prepare_audio_routing()
        _kill_stale_gpio_holders()
        from pidog import Pidog
        log.info("Initializing PiDog hardware (servos, sensors, RGB)...")
        _dog = Pidog()
        time.sleep(_startup_wait_sec)
        atexit.register(_shutdown)
    return _dog


def flow():
    global _flow
    if _flow is not None:
        return _flow
    with _lock:
        if _flow is not None:
            return _flow
        from pidog.action_flow import ActionFlow
        _flow = ActionFlow(dog())
    return _flow


def camera_snapshot_b64() -> str:
    """JPEG snapshot (512×512, q=75) as base64 — large enough for GPT-4o
    `detail="low"` (85 tokens fixed), small enough for transmission.

    On a camera timeout (the Pi camera frontend occasionally hangs, typically
    with a wobbly ribbon cable) a single close+start usually makes the stream
    available again.
    """
    global _camera_started
    import base64
    import cv2
    from vilib import Vilib

    def _ensure_started() -> None:
        global _camera_started
        if not _camera_started:
            log.info("starting camera (vilib)...")
            Vilib.camera_start(vflip=False, hflip=False)
            _camera_started = True
            time.sleep(1.5)

    def _restart() -> None:
        global _camera_started
        log.warning("camera timeout — restarting vilib...")
        try:
            Vilib.camera_close()
        except Exception as exc:
            log.warning("camera_close on restart failed: %s", exc)
        _camera_started = False
        time.sleep(0.3)
        _ensure_started()

    def _sig(frame) -> int:
        # Cheap fingerprint: sum of a sparse sample. Changes on any real new
        # frame, ~free to compute. Avoids hashing the full array every call.
        return int(frame[::32, ::32].sum())

    global _cam_last_sig, _cam_frozen_count, _cam_last_fresh

    with _lock:
        _ensure_started()
    img = Vilib.img
    if img is None:
        time.sleep(0.5)
        img = Vilib.img
    if img is None:
        # No frame at all → restart the stream and wait again.
        with _lock:
            _restart()
        time.sleep(0.3)
        img = Vilib.img
    if img is None:
        raise RuntimeError("camera frame not available (after restart)")

    # Freeze detection: same frame repeatedly → frontend hung, restart even
    # though Vilib.img is not None.
    sig = _sig(img)
    if sig == _cam_last_sig:
        _cam_frozen_count += 1
        if _cam_frozen_count >= _CAM_FREEZE_LIMIT:
            log.warning("camera frozen (%d identical frames) — restarting",
                        _cam_frozen_count)
            with _lock:
                _restart()
            time.sleep(0.3)
            img = Vilib.img if Vilib.img is not None else img
            _cam_frozen_count = 0
            sig = _sig(img)
    else:
        _cam_frozen_count = 0
        _cam_last_fresh = time.time()
    _cam_last_sig = sig

    # Resize to max 512×512 (keep aspect ratio) + JPEG encode q=75
    h, w = img.shape[:2]
    scale = 512 / max(h, w)
    if scale < 1.0:
        img = cv2.resize(img, (int(w * scale), int(h * scale)))
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 75])
    if not ok:
        raise RuntimeError("jpeg encode failed")
    return base64.b64encode(buf).decode("ascii")


def camera_fresh_age_s() -> float:
    """Seconds since the camera last produced a genuinely new frame.
    -1 if no fresh frame seen yet (camera never delivered)."""
    if _cam_last_fresh == 0.0:
        return -1.0
    return round(time.time() - _cam_last_fresh, 1)


def is_initialized() -> bool:
    return _dog is not None


def _shutdown() -> None:
    global _dog, _camera_started
    if _camera_started:
        try:
            from vilib import Vilib
            Vilib.camera_close()
        except Exception:
            pass
        _camera_started = False
    if _dog is None:
        return
    log.info("Shutting down PiDog (stop_and_lie + close)...")
    try:
        _dog.close()
    except Exception as exc:
        log.error("Error closing PiDog: %s", exc)
    finally:
        _dog = None


def shutdown() -> None:
    _shutdown()
