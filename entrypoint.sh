#!/bin/bash
# Starts a dummy web server on the port Hugging Face's health check expects,
# then runs main.py, restarting it whenever it exits — whether from a crash
# or from a stop signal. An earlier version of this script exited instead of
# restarting after a signal, on the assumption Hugging Face would always
# promptly replace the container with a freshly built one. That assumption
# didn't hold in practice — a stop signal doesn't reliably mean a
# replacement is coming right away, so exiting left the bot down with
# nothing to bring it back. This version still forwards the signal to
# main.py first, giving it a chance to close its Telegram session cleanly,
# but always restarts afterward regardless of why it exited. If the whole
# container is genuinely being torn down for a real redeploy, this restart
# is harmless — the container disappears along with it moments later either
# way.

# Served from an isolated, empty directory — never /app — so this can't
# expose .git or any other repo file over HTTP.
mkdir -p /tmp/healthcheck
echo "ok" > /tmp/healthcheck/index.html
python3 -m http.server 7860 --directory /tmp/healthcheck &

child=0

forward_signal() {
    echo "Received stop signal — forwarding to bot."
    if [ "$child" -ne 0 ]; then
        kill -TERM "$child" 2>/dev/null
    fi
}

trap forward_signal TERM INT

while true; do
    python3 main.py &
    child=$!
    wait "$child"
    echo "main.py exited — restarting in 3s"
    sleep 3
done
