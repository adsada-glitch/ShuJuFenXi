"""Small reproducible Taobao Kafka/Flink experiment. Python 3.11+, standard library preparation."""
import argparse
import csv
import hashlib
import json
import re
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

TZ = timezone(timedelta(hours=8))
BEHAVIORS = {'pv', 'fav', 'cart', 'buy'}


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def parse_row(row):
    if len(row) != 5:
        raise ValueError('expected five fields')
    user, item, category, behavior, ts = row
    event = dict(user_id=int(user), item_id=int(item), category_id=int(category),
                 behavior=behavior.strip(), ts=int(ts))
    if event['behavior'] not in BEHAVIORS or min(event['user_id'], event['item_id'], event['category_id'], event['ts']) < 0:
        raise ValueError('invalid behavior or negative identifier/timestamp')
    return event


def aggregate(events):
    counts = Counter(e['behavior'] for e in events)
    users = {e['user_id'] for e in events}
    buyers = {e['user_id'] for e in events if e['behavior'] == 'buy'}
    return dict(total_events=len(events), active_users=len(users), pv=counts['pv'],
                fav=counts['fav'], cart=counts['cart'], buy_events=counts['buy'], buyers=len(buyers))


def reference(events):
    windows = defaultdict(list)
    hours = Counter()
    categories = Counter()
    daily = defaultdict(list)
    for e in events:
        stamp = datetime.fromtimestamp(e['ts'], TZ)
        daily[stamp.date()].append(e)
        bucket = stamp.replace(minute=stamp.minute // 5 * 5, second=0, microsecond=0)
        windows[bucket.strftime('%Y-%m-%d %H:%M:%S')].append(e)
        if e['behavior'] == 'buy':
            hours[stamp.strftime('%Y-%m-%d %H:00:00')] += 1
            categories[str(e['category_id'])] += 1
    cumulative = {}
    for day, items in daily.items():
        midnight = datetime.combine(day, datetime.min.time(), TZ)
        active = set()
        cursor = 0
        items = sorted(items, key=lambda e: e['ts'])
        for step in range(1, 145):
            end = midnight + timedelta(minutes=step * 10)
            while cursor < len(items) and items[cursor]['ts'] < end.timestamp():
                active.add(items[cursor]['user_id'])
                cursor += 1
            if active:
                cumulative[end.strftime('%Y-%m-%d %H:%M:%S')] = len(active)
    return {'overall': aggregate(events),
            'windows': {key: aggregate(value) for key, value in sorted(windows.items())},
            'hours': dict(sorted(hours.items())),
            'categories': dict(sorted(categories.items())), 'cumulative': cumulative}


def prepare(args):
    if args.limit < 1:
        raise ValueError('limit must be positive')
    events, invalid, out_of_range, duplicates, seen = [], 0, 0, 0, set()
    read = 0
    with open(args.csv, encoding='utf-8-sig', newline='') as source:
        for row in csv.reader(source):
            read += 1
            try:
                event = parse_row(row)
                day = datetime.fromtimestamp(event['ts'], TZ).strftime('%Y-%m-%d')
            except (ValueError, OverflowError, OSError):
                invalid += 1
                if read >= args.limit:
                    break
                continue
            if not '2017-11-25' <= day <= '2017-12-03':
                out_of_range += 1
            else:
                key = tuple(event.values())
                if key in seen:
                    duplicates += 1
                seen.add(key)
                events.append(event)
            if read >= args.limit:
                break
    # Keep duplicate records: this baseline measures input behavior records, not deduplicated events.
    events.sort(key=lambda e: e['ts'])
    target = Path(args.out)
    target.mkdir(parents=True, exist_ok=True)
    raw = ''.join(json.dumps(e, separators=(',', ':')) + '\n' for e in events)
    (target / 'events.jsonl').write_text(raw, encoding='utf-8')
    manifest = dict(input_rows=read, accepted_rows=len(events), invalid_rows=invalid,
                    out_of_range_rows=out_of_range, duplicate_records=duplicates,
                    duplicate_policy='kept', timezone='Asia/Shanghai',
                    selection='first N source rows, date-filtered, sorted by event time',
                    sha256=hashlib.sha256(raw.encode()).hexdigest())
    write_json(target / 'manifest.json', manifest)
    write_json(target / 'expected.json', reference(events))
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


def names(run):
    if not re.fullmatch(r'[a-z][a-z0-9_]{0,48}', run):
        raise ValueError('run must match [a-z][a-z0-9_]{0,48}')
    return {key: f'{run}_{key}' for key in ('events', 'overall', 'windows', 'hours', 'categories', 'cumulative')}


def replay(args):
    from kafka import KafkaProducer, KafkaAdminClient
    from kafka.admin import NewTopic
    topics = names(args.run)
    if args.rate <= 0:
        raise ValueError('rate must be positive')
    source = Path(args.data) / 'events.jsonl'
    manifest = json.loads((Path(args.data) / 'manifest.json').read_text(encoding='utf-8'))
    if hashlib.sha256(source.read_bytes()).hexdigest() != manifest['sha256']:
        raise ValueError('input hash differs from manifest; prepare again')
    admin = KafkaAdminClient(bootstrap_servers=args.bootstrap)
    try:
        existing = set(admin.list_topics()) & set(topics.values())
        if existing:
            raise ValueError(f'run topics already exist: {existing}. Use a NEW --run to avoid duplicate replay.')
        admin.create_topics([NewTopic(name, 1, 1, topic_configs={
            'retention.ms': '604800000', 'retention.bytes': '1073741824',
            'cleanup.policy': 'delete' if key == 'events' else 'compact'})
            for key, name in topics.items()])
    finally:
        admin.close()
    producer = KafkaProducer(bootstrap_servers=args.bootstrap, acks='all', enable_idempotence=True,
                             value_serializer=lambda x: json.dumps(x).encode())
    sent = 0
    try:
        with source.open(encoding='utf-8') as stream:
            for line in stream:
                started = time.monotonic()
                producer.send(topics['events'], json.loads(line)).get(timeout=30)
                sent += 1
                if sent % 1000 == 0:
                    print(f'confirmed {sent}', flush=True)
                time.sleep(max(0, 1 / args.rate - (time.monotonic() - started)))
    finally:
        producer.close(timeout=10)
    write_json(Path(args.data) / 'replay_receipt.json', dict(run=args.run, confirmed=sent, topics=topics))
    print(f'confirmed={sent}; run={args.run}', flush=True)


def sql(args):
    t = names(args.run)
    if not re.fullmatch(r'[A-Za-z0-9.:-]+', args.bootstrap):
        raise ValueError('invalid bootstrap address')
    def sink(name, columns, keys):
        return f"CREATE TABLE {name} ({columns}, PRIMARY KEY ({keys}) NOT ENFORCED) WITH (\n" + \
            f"'connector'='upsert-kafka','topic'='{t[name]}','properties.bootstrap.servers'='{args.bootstrap}'," + \
            "'key.format'='json','value.format'='json');\n"
    metrics = 'total_events BIGINT, active_users BIGINT, pv BIGINT, fav BIGINT, cart BIGINT, buy_events BIGINT, buyers BIGINT'
    expr = "COUNT(*), COUNT(DISTINCT user_id), SUM(CASE WHEN behavior='pv' THEN 1 ELSE 0 END), SUM(CASE WHEN behavior='fav' THEN 1 ELSE 0 END), SUM(CASE WHEN behavior='cart' THEN 1 ELSE 0 END), SUM(CASE WHEN behavior='buy' THEN 1 ELSE 0 END), COUNT(DISTINCT CASE WHEN behavior='buy' THEN user_id END)"
    bounded = "'scan.bounded.mode'='latest-offset'," if not args.live else ''
    if args.end_offset is not None:
        if args.live or args.end_offset < 1:
            raise ValueError('--end-offset must be positive and cannot combine with --live')
        bounded = f"'scan.bounded.mode'='specific-offsets','scan.bounded.specific-offsets'='partition:0,offset:{args.end_offset}',"
    text = "SET 'parallelism.default' = '1';\nSET 'table.local-time-zone' = 'Asia/Shanghai';\n"
    if not 0 <= args.watermark_seconds <= 86400:
        raise ValueError('watermark must be between 0 and 86400 seconds')
    hours, remainder = divmod(args.watermark_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    watermark = f'{hours:02d}:{minutes:02d}:{seconds:02d}'
    text += f"CREATE TABLE events (user_id BIGINT,item_id BIGINT,category_id BIGINT,behavior STRING,ts BIGINT, event_time AS TO_TIMESTAMP_LTZ(ts,0), WATERMARK FOR event_time AS event_time - INTERVAL '{watermark}' HOUR TO SECOND) WITH ("
    text += f"'connector'='kafka','topic'='{t['events']}','properties.bootstrap.servers'='{args.bootstrap}','properties.group.id'='{args.run}_flink','scan.startup.mode'='earliest-offset',{bounded}'format'='json');\n"
    text += sink('overall', 'metric_key STRING,' + metrics, 'metric_key')
    text += sink('windows', 'window_start STRING,' + metrics, 'window_start')
    text += sink('hours', 'hour_start STRING, buy_events BIGINT', 'hour_start')
    text += sink('categories', 'category_id BIGINT, buy_events BIGINT', 'category_id')
    text += sink('cumulative', 'window_end STRING, uv BIGINT', 'window_end')
    text += 'EXECUTE STATEMENT SET BEGIN\n'
    text += f"INSERT INTO overall SELECT 'all',{expr} FROM events;\n"
    text += f"INSERT INTO windows SELECT DATE_FORMAT(window_start,'yyyy-MM-dd HH:mm:ss'),{expr} FROM TABLE(TUMBLE(TABLE events,DESCRIPTOR(event_time),INTERVAL '5' MINUTE)) GROUP BY window_start,window_end;\n"
    text += "INSERT INTO hours SELECT DATE_FORMAT(window_start,'yyyy-MM-dd HH:mm:ss'),COUNT(*) FROM TABLE(TUMBLE(TABLE events,DESCRIPTOR(event_time),INTERVAL '1' HOUR)) WHERE behavior='buy' GROUP BY window_start,window_end;\n"
    text += "INSERT INTO categories SELECT category_id,COUNT(*) FROM events WHERE behavior='buy' GROUP BY category_id;\n"
    text += "INSERT INTO cumulative SELECT DATE_FORMAT(window_end,'yyyy-MM-dd HH:mm:ss'),COUNT(DISTINCT user_id) FROM TABLE(CUMULATE(TABLE events,DESCRIPTOR(event_time),INTERVAL '10' MINUTE,INTERVAL '1' DAY)) GROUP BY window_start,window_end;\nEND;\n"
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(text, encoding='utf-8')
    print(args.out)


def collect(args):
    from kafka import KafkaConsumer, TopicPartition
    topics = names(args.run)
    consumer = KafkaConsumer(bootstrap_servers=args.bootstrap, enable_auto_commit=False,
                             value_deserializer=lambda b: json.loads(b) if b else None)
    partitions = [TopicPartition(topics[key], 0) for key in ('overall','windows','hours','categories','cumulative')]
    consumer.assign(partitions)
    for partition, start in consumer.beginning_offsets(partitions).items():
        consumer.seek(partition, start)
    # Capture explicit end offsets. Caller waits for Flink FINISHED first.
    ends = consumer.end_offsets(partitions)
    rows = {key: {} for key in ('overall','windows','hours','categories','cumulative')}
    mapping = {topics[k]: k for k in rows}
    key_fields = dict(overall='metric_key',windows='window_start',hours='hour_start',categories='category_id',cumulative='window_end')
    deadline = time.monotonic() + 90
    try:
        while any(consumer.position(p) < ends[p] for p in partitions):
            if time.monotonic() > deadline:
                raise TimeoutError('result snapshot timed out')
            for partition, messages in consumer.poll(timeout_ms=1000).items():
                kind = mapping[partition.topic]
                for message in messages:
                    if message.offset >= ends[partition]:
                        continue
                    key = str(json.loads(message.key)[key_fields[kind]])
                    if message.value is None:
                        rows[kind].pop(key, None)
                    else:
                        rows[kind][key] = message.value
    finally:
        consumer.close()
    def metrics(row):
        return {k: row[k] for k in ('total_events','active_users','pv','fav','cart','buy_events','buyers')}
    actual = dict(overall=metrics(rows['overall']['all']) if 'all' in rows['overall'] else {},
                  windows={k: metrics(v) for k,v in rows['windows'].items()},
                  hours={k:v['buy_events'] for k,v in rows['hours'].items()},
                  categories={k:v['buy_events'] for k,v in rows['categories'].items()},
                  cumulative={k:v['uv'] for k,v in rows['cumulative'].items()})
    expected = json.loads((Path(args.data)/'expected.json').read_text(encoding='utf-8'))
    checks = {key: actual[key] == expected[key] for key in expected}
    report = dict(run=args.run, source='Flink result topics', checks=checks,
                  passed=all(checks.values()), actual=actual,
                  manifest=json.loads((Path(args.data)/'manifest.json').read_text(encoding='utf-8')))
    write_json(args.out, report)
    print(json.dumps(checks, indent=2))
    if not report['passed']:
        raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare'); p.add_argument('--csv',required=True); p.add_argument('--limit',type=int,default=10000); p.add_argument('--out',default='data/sample')
    p.set_defaults(function=prepare)
    p = sub.add_parser('replay'); p.add_argument('--data',default='data/sample'); p.add_argument('--run',required=True); p.add_argument('--rate',type=float,default=100); p.add_argument('--bootstrap',default='192.168.121.134:9092'); p.set_defaults(function=replay)
    p = sub.add_parser('sql'); p.add_argument('--run',required=True); p.add_argument('--bootstrap',default='192.168.121.134:9092'); p.add_argument('--out',default='sql/analysis.sql'); p.add_argument('--live',action='store_true'); p.add_argument('--end-offset',type=int); p.add_argument('--watermark-seconds',type=int,default=5); p.set_defaults(function=sql)
    p = sub.add_parser('collect'); p.add_argument('--run',required=True); p.add_argument('--data',default='data/sample'); p.add_argument('--out',default='reports/result.json'); p.add_argument('--bootstrap',default='192.168.121.134:9092'); p.set_defaults(function=collect)
    args=parser.parse_args(); args.function(args)


if __name__ == '__main__':
    main()
