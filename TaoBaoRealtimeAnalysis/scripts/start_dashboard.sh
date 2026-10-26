#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p runtime
if [[ -f runtime/dashboard.pid ]] && kill -0 "$(cat runtime/dashboard.pid)" 2>/dev/null; then
  echo 'Dashboard is already running; inspect runtime/dashboard.pid'; exit 1
fi
nohup "${PYTHON:-/export/taobao-stream/.venv/bin/python}" dashboard.py --host 192.168.121.134 --port 8090 > runtime/dashboard.log 2>&1 < /dev/null &
echo $! > runtime/dashboard.pid
printf 'Dashboard: http://192.168.121.134:8090 (PID %s)\n' "$!"
