#!/bin/bash
# Keeps the bot running on a Hugging Face Space.
#
#  * serves a tiny placeholder page on port 7860 so the Space shows "Running"
#  * runs "python3 main.py" and starts it again whenever it exits (crash, the
#    watchdog in keepalive.py restarting a wedged connection, ...)
#  * stops for good ONLY when this script itself receives SIGTERM/SIGINT, i.e.
#    when you pause or restart the Space yourself

HEALTH_PORT="${HEALTH_PORT:-7860}"
HEALTH_DIR="/tmp/healthcheck"
MIN_DELAY="${RESTART_MIN_DELAY:-3}"          # seconds to wait before restarting
MAX_DELAY="${RESTART_MAX_DELAY:-60}"         # ...doubling up to this if it keeps crashing
STABLE_AFTER="${RESTART_STABLE_AFTER:-60}"   # ran at least this long = not a crash loop

stopping=0
child=""
export BOT_SUPERVISED=1   # tells the bot a supervisor restarts it, so its watchdog just exits

log() { echo "[entrypoint] $*"; }

on_stop() {
    stopping=1
    log "stop signal received, shutting the bot down"
    if [ -n "$child" ]; then
        kill -TERM "$child" 2>/dev/null
    fi
}
trap on_stop TERM INT

# Placeholder web server. It only serves this one folder (never the bot's code or
# .git) and starts itself again if it ever dies.
mkdir -p "$HEALTH_DIR"
echo "ok" > "$HEALTH_DIR/index.html"
(
    trap 'kill "$server" 2>/dev/null; exit 0' TERM
    while true; do
        python3 -m http.server "$HEALTH_PORT" --bind 0.0.0.0 --directory "$HEALTH_DIR" &
        server=$!
        wait "$server"
        sleep 1
    done
) &
web_loop=$!

delay="$MIN_DELAY"
while [ "$stopping" -eq 0 ]; do
    started=$SECONDS
    python3 main.py &
    child=$!
    log "bot started (pid $child)"

    # wait returns early when a trapped signal arrives, so keep waiting until the
    # process is really gone. That guarantees two bots never run at the same time.
    rc=0
    while kill -0 "$child" 2>/dev/null; do
        wait "$child"
        rc=$?
    done
    child=""
    ran=$(( SECONDS - started ))

    if [ "$stopping" -eq 1 ]; then
        log "bot stopped (exit code $rc)"
        break
    fi

    log "bot exited with code $rc after ${ran}s"
    if [ "$ran" -ge "$STABLE_AFTER" ]; then
        delay="$MIN_DELAY"
    fi
    log "restarting in ${delay}s"
    sleep "$delay" &
    wait $!
    delay=$(( delay * 2 ))
    if [ "$delay" -gt "$MAX_DELAY" ]; then
        delay="$MAX_DELAY"
    fi
done

kill "$web_loop" 2>/dev/null
exit 0
