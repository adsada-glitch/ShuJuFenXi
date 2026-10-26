"""Actual Flink late-event experiment. Run on 101 with SSH access to 102."""
import argparse
import json
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from kafka import KafkaAdminClient, KafkaProducer
from kafka.admin import NewTopic
import project


def status(job):
    with urllib.request.urlopen(f'http://192.168.121.135:8081/jobs/{job}', timeout=10) as response:
        return json.load(response)['state']


def trial(run, watermark):
    topics=project.names(run)
    admin=KafkaAdminClient(bootstrap_servers='192.168.121.134:9092')
    try:
        if set(topics.values()) & set(admin.list_topics()):
            raise ValueError('Experiment run exists; choose another prefix')
        admin.create_topics([NewTopic(t,1,1) for t in topics.values()])
    finally: admin.close()
    data=Path('data')/run;data.mkdir(parents=True,exist_ok=True)
    base=1511539200
    # Deliberately send 00:01 after 00:11; sleep allows the watermark to advance.
    events=[dict(user_id=i+1,item_id=1,category_id=1,behavior=b,ts=base+delta)
            for i,(delta,b) in enumerate([(0,'buy'),(660,'pv'),(60,'buy'),(1260,'pv')])]
    project.write_json(data/'expected.json',project.reference(events))
    project.write_json(data/'manifest.json',dict(input_rows=4,accepted_rows=4,selection='synthetic late-event experiment',timezone='Asia/Shanghai'))
    sql_path=Path('sql')/(run+'.sql')
    project.sql(argparse.Namespace(run=run,bootstrap='192.168.121.134:9092',out=str(sql_path),live=False,end_offset=4,watermark_seconds=watermark))
    subprocess.run(['scp',str(sql_path),'root@hadoop102:/export/taobao-realtime/experiment.sql'],check=True)
    result=subprocess.run(['ssh','root@hadoop102','JAVA_HOME=/export/servers/jdk /export/servers/flink-1.17.2/bin/sql-client.sh -f /export/taobao-realtime/experiment.sql'],text=True,capture_output=True,check=True)
    match=re.search(r'Job ID: ([a-f0-9]{32})',result.stdout)
    if not match: raise RuntimeError(result.stdout+result.stderr)
    job=match[1]
    for _ in range(30):
        state=status(job)
        if state=='RUNNING': break
        if state in ('FAILED','CANCELED'): raise RuntimeError(state)
        time.sleep(1)
    else: raise TimeoutError('Flink did not reach RUNNING')
    producer=KafkaProducer(bootstrap_servers='192.168.121.134:9092',acks='all',enable_idempotence=True,value_serializer=lambda v:json.dumps(v).encode())
    try:
        for e in events:
            producer.send(topics['events'],e).get(timeout=30)
            time.sleep(3)
    finally: producer.close()
    for _ in range(60):
        state=status(job)
        if state=='FINISHED': break
        if state in ('FAILED','CANCELED'): raise RuntimeError(state)
        time.sleep(1)
    else: raise TimeoutError('experiment did not finish')
    output=Path('reports')/(run+'.json')
    try:
        project.collect(argparse.Namespace(run=run,bootstrap='192.168.121.134:9092',data=str(data),out=str(output)))
    except SystemExit as exc:
        if exc.code != 1: raise
    report=json.loads(output.read_text())
    return dict(run=run,job=job,watermark_seconds=watermark,input_events=4,
                overall_events=report['actual']['overall']['total_events'],
                window_events=sum(v['total_events'] for v in report['actual']['windows'].values()),
                window_buys=sum(v['buy_events'] for v in report['actual']['windows'].values()))


if __name__=='__main__':
    prefix=sys.argv[1] if len(sys.argv)>1 else 'late_'+time.strftime('%Y%m%d_%H%M%S')
    results=[trial(prefix+'_short',5),trial(prefix+'_wide',1200)]
    report=dict(experiment='same four events, different watermark tolerance',results=results,
                verified=(results[0]['window_events']==3 and results[1]['window_events']==4))
    project.write_json('reports/late_experiment.json',report)
    print(json.dumps(report,indent=2),flush=True)
    if not report['verified']: raise SystemExit('Observed late-event outcome differs; inspect timing')
