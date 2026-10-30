#!/usr/bin/env bash
# SatarkPay - one command to run, test or retrain.
#   ./run.sh            start the app on http://localhost:8000
#   ./run.sh wifi       start so that phones on the same Wi-Fi or hotspot can join (prints the address and pairing code)
#   ./run.sh demo       serve the test pages with fake scam links for the browser extension
#   ./run.sh accounts   make new passwords for the user, merchant and admin logins
#   ./run.sh test       run all tests
#   ./run.sh train      rebuild the simulated world and retrain both models (about 2 minutes)
#   ./run.sh evaluate   measure everything again and write models/metrics.json (about 4 minutes)
#   ./run.sh paysim     run the public PaySim benchmark (downloads about 490 MB the first time)
#   ./run.sh loadtest   measure real latency and throughput (the app must not be running)
#   ./run.sh phone      keep an Android phone connected over USB (run in a second terminal)
set -euo pipefail
cd "$(dirname "$0")"

# (Re)create the environment when it is missing or was made by a different Python.
if ! .venv/bin/python -c "import fastapi, sklearn, xgboost, tldextract, uvicorn, segno" 2>/dev/null; then
  if .venv/bin/python -c "import sys" 2>/dev/null; then
    echo "Installing missing Python packages (needs internet)..."
  else
    echo "Creating the Python environment (first run only, needs internet)..."
    rm -rf .venv
    python3 -m venv .venv
  fi
  .venv/bin/python -m pip install --quiet --disable-pip-version-check -r requirements.txt -r requirements-dev.txt
fi
PY=.venv/bin/python
HOST="${SATARK_HOST:-127.0.0.1}"
PORT="${SATARK_PORT:-8000}"

case "${1:-serve}" in
  accounts)
    exec "$PY" -m app.auth --reset
    ;;
  serve)
    "$PY" -m app.auth
    echo "SatarkPay is starting on http://${HOST}:${PORT}  (Ctrl+C to stop)"
    exec "$PY" -m uvicorn app.main:app --host "$HOST" --port "$PORT"
    ;;
  wifi)
    "$PY" -m app.auth
    # The pairing code lets the SatarkPay app talk to this laptop. It stays in .env, which is never committed.
    if ! grep -qs "^SATARK_TOKEN=" .env; then
      echo "SATARK_TOKEN=$("$PY" -c "import secrets; print(secrets.token_urlsafe(9))")" >> .env
    fi
    echo "SatarkPay in Wi-Fi mode. Open the dashboard on this laptop: http://127.0.0.1:${PORT}"
    echo "Phones on the same network open one of these:"
    { [ -f /.flatpak-info ] && flatpak-spawn --host hostname -I || hostname -I; } 2>/dev/null | tr " " "\n" |
      grep -E "^(10|172\.(1[6-9]|2[0-9]|3[01])|192\.168)\." | grep -v -E "^172\.(1[7-9]|2[0-2])\.0\.1$|^192\.168\.122\.1$|^10\.0\.3\.1$" |
      sed "s|.*|   http://&:${PORT}/pay|"
    echo "Pairing code for the SMS Guard app: $(grep "^SATARK_TOKEN=" .env | cut -d= -f2-)"
    SATARK_HOST=0.0.0.0 exec "$PY" -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
    ;;
  demo)
    # Test pages with fake scam links for the Link Guard extension. Keep ./run.sh running too.
    echo "Demo pages: http://127.0.0.1:8765/  (Ctrl+C to stop)"
    exec "$PY" -m http.server 8765 --bind 127.0.0.1 --directory demo
    ;;
  test)
    shift
    exec "$PY" -m pytest "$@"
    ;;
  train)
    exec "$PY" -m ml.train --refresh
    ;;
  evaluate)
    exec "$PY" -m ml.evaluate --refresh
    ;;
  paysim)
    exec "$PY" -m ml.paysim_benchmark
    ;;
  loadtest)
    exec "$PY" scripts/loadtest.py
    ;;
  phone)
    # Keeps the USB link to the phone alive: the phone's 127.0.0.1:8000 reaches this laptop.
    ADB="$(command -v adb || echo "$HOME/Android/Sdk/platform-tools/adb")"
    RUN=""
    [ -f /.flatpak-info ] && RUN="flatpak-spawn --host"     # VS Code Flatpak: adb lives on the host
    echo "Keeping the phone connected over USB (Ctrl+C to stop). In the app use http://127.0.0.1:8000"
    while true; do
      for d in $($RUN "$ADB" devices | awk 'NR>1 && $2=="device" && $1 !~ /^emulator-/ {print $1}'); do
        $RUN "$ADB" -s "$d" reverse --list 2>/dev/null | grep -q "tcp:8000" ||
          { $RUN "$ADB" -s "$d" reverse tcp:8000 tcp:8000 >/dev/null 2>&1 && echo "$(date +%H:%M:%S) phone $d connected"; }
      done
      sleep 5
    done
    ;;
  *)
    echo "Usage: ./run.sh [serve|wifi|demo|accounts|test|train|evaluate|paysim|loadtest|phone]"
    exit 2
    ;;
esac
