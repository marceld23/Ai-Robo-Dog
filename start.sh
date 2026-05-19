#!/bin/bash
# Start Buddy (aidog web UI on port 8080).
#
# Usage:
#   ./start.sh                  # foreground, logs to stdout, Ctrl+C to quit
#   ./start.sh --background     # in the background, logs to /tmp/aidog.log
#   PORT=9000 ./start.sh        # different port
#   PAUSED=1 ./start.sh         # boot inert; act only after Web UI "Resume"
#
# Env:
#   PAUSED=1   pass --start-paused (safe default for unattended starts)
#   PORT, HOST override bind
set -eu

cd "$(dirname "$0")"

PORT="${PORT:-8080}"
HOST="${HOST:-0.0.0.0}"
PAUSED_FLAG=""
[ "${PAUSED:-0}" = "1" ] && PAUSED_FLAG="--start-paused"

# Clean up old hangs — previous web process or stuck Pidog init.
if pgrep -f "main\.py (web|listen)" > /dev/null; then
    echo ">> alte aidog-Prozesse gefunden, killing..."
    pkill -9 -f "main\.py (web|listen)" || true
    sleep 3
fi

# Dog sound assets belong to SunFounder (GPLv3) and are not redistributed in
# this repo. Copy them from the local SunFounder install on first run.
SOUNDS_DIR="aidog/sounds"
if [ ! -f "$SOUNDS_DIR/single_bark_1.mp3" ]; then
    if [ -d "$HOME/pidog/sounds" ]; then
        echo ">> copying dog sounds from ~/pidog/sounds ..."
        mkdir -p "$SOUNDS_DIR"
        cp "$HOME"/pidog/sounds/*.mp3 "$HOME"/pidog/sounds/*.wav "$SOUNDS_DIR"/ 2>/dev/null || true
    else
        echo ">> WARNING: ~/pidog/sounds not found — dog will be mute."
    fi
fi

# Warn early if the Vosk model for the configured language is missing.
LANG_CFG=$(grep -m1 '^language:' config.yaml | awk '{print $2}')
case "$LANG_CFG" in
  en) VOSK_DIR="models/vosk-model-small-en-us-0.15" ;;
  *)  VOSK_DIR="models/vosk-model-small-de-0.15" ;;
esac
if [ ! -d "$VOSK_DIR" ]; then
    echo ">> WARNING: Vosk model '$VOSK_DIR' missing (language=$LANG_CFG)."
    echo ">> See README 'Setup' for the download command."
fi

# pyaudio/SDL backend explicitly to PipeWire-Pulse — otherwise SDL picks a
# default driver that bypasses the voicehat routing (no audio output).
export SDL_AUDIODRIVER=pulse

PI_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
echo ">> Buddy startet auf http://${PI_IP:-localhost}:${PORT}"
echo ">> 45 Tools, Wake-Word hey-buddy, Touch + Ultraschall + Sound + Battery"

[ -n "$PAUSED_FLAG" ] && echo ">> start-paused: no LLM calls until you click Resume in the Web UI"

if [ "${1:-}" = "--background" ]; then
    LOG="/tmp/aidog.log"
    nohup uv run python main.py web --host "$HOST" --port "$PORT" $PAUSED_FLAG \
        > "$LOG" 2>&1 &
    PID=$!
    echo ">> PID $PID · Logs: tail -f $LOG"
    echo ">> Stoppen: kill $PID  (oder pkill -f 'main.py web')"
    exit 0
fi

exec uv run python main.py web --host "$HOST" --port "$PORT" $PAUSED_FLAG
