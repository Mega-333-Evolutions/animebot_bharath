#!/bin/bash
# Runs main.py, restarting it if it crashes on its own — but if this script
# receives a stop signal (e.g. Hugging Face stopping/restarting the Space),
# it forwards that signal to main.py, waits for it to shut down cleanly,
# and exits instead of relaunching. Without this, a bare restart loop
# swallows the signal and the container never actually stops.

child=0

term_handler() {
    echo "Received stop signal — forwarding to bot and shutting down."
    if [ "$child" -ne 0 ]; then
        kill -TERM "$child" 2>/dev/null
        wait "$child"
    fi
    exit 0
}

trap term_handler TERM INT

while true; do
    python3 main.py &
    child=$!
    wait "$child"
    echo "main.py exited — restarting in 3s"
    sleep 3
done
