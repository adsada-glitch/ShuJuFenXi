#!/usr/bin/env bash
# Run on hadoop101. Existing Kafka, Flink and SSH access to hadoop102 required.
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON=${PYTHON:-/export/taobao-stream/.venv/bin/python}
CSV=${CSV:-/mnt/taobao/UserBehavior.csv}
LIMIT=${LIMIT:-10000}
RATE=${RATE:-200}
RUN=${RUN:-tb_$(date +%Y%m%d_%H%M%S)}
mkdir -p runtime sql reports
"$PYTHON" project.py prepare --csv "$CSV" --limit "$LIMIT" --out data/sample
"$PYTHON" project.py replay --data data/sample --run "$RUN" --rate "$RATE"
"$PYTHON" project.py sql --run "$RUN" --out sql/analysis.sql
ssh root@hadoop102 'mkdir -p /export/taobao-realtime'
scp sql/analysis.sql root@hadoop102:/export/taobao-realtime/analysis.sql
ssh root@hadoop102 'JAVA_HOME=/export/servers/jdk /export/servers/flink-1.17.2/bin/sql-client.sh -f /export/taobao-realtime/analysis.sql' > runtime/submit.log 2>&1
JOB=$(sed -n 's/.*Job ID: \([a-f0-9]\{32\}\).*/\1/p' runtime/submit.log | tail -n 1)
if [[ ! "$JOB" =~ ^[a-f0-9]{32}$ ]]; then cat runtime/submit.log; exit 1; fi
"$PYTHON" scripts/wait_job.py "$JOB"
"$PYTHON" project.py collect --run "$RUN" --data data/sample --out reports/result.json
"$PYTHON" dashboard.py --report reports/result.json --export reports/dashboard.html
printf 'Completed run=%s job=%s\n' "$RUN" "$JOB"
