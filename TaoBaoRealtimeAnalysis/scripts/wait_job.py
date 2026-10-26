import json
import sys
import time
import urllib.request
from pathlib import Path

job = sys.argv[1]
for _ in range(150):
    with urllib.request.urlopen(f'http://192.168.121.135:8081/jobs/{job}', timeout=10) as response:
        result = json.load(response)
    state = result['state']
    if state == 'FINISHED':
        Path('reports').mkdir(exist_ok=True)
        Path('reports/flink_job.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(f'{job}: FINISHED')
        break
    if state in ('FAILED', 'CANCELED', 'SUSPENDED'):
        raise SystemExit(f'{job}: {state}; inspect Flink dashboard exceptions')
    time.sleep(2)
else:
    raise SystemExit('Timed out after approximately 5 minutes; job not automatically canceled')
