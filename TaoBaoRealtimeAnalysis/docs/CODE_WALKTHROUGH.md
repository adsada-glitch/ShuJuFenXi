# 淘宝用户行为实时分析：完整实现与代码解析

## 1. 项目目标与实现路线

项目围绕淘宝用户的浏览、收藏、加购和购买记录，构建从数据质量检查、事件回放、流式聚合到结果验证和可视化的完整流程。使用历史 CSV 模拟事件输入，以事件发生时间计算指标，并通过独立的 Python 计算结果检验 Flink 输出。

技术栈为 Python 3.11、kafka-python 2.2.15、Kafka 3.7.2 KRaft、Flink 1.17.2 SQL，以及 HTML/CSS/JavaScript。hadoop101 承担消息接入、基准计算和展示，hadoop102 承担 Flink 计算。项目采用单 Kafka 节点、单 TaskManager、并行度 1，完成低资源环境下的端到端验证。

```text
UserBehavior.csv
  → 字段校验、日期筛选、事件时间排序
  → events.jsonl + manifest.json + expected.json
  → Kafka 输入主题
  → Flink SQL 五组聚合
  → Kafka upsert 结果主题
  → 按主键还原结果 → Python 基准对账 → 报告与看板
```

|源字段|程序字段|含义|
|---|---|---|
|user_id|user_id|匿名用户 ID|
|item_id|item_id|匿名商品 ID|
|category_id|category_id|匿名商品类目 ID|
|behavior_type|behavior|pv、fav、cart、buy 四类行为|
|timestamp|ts|Unix 秒级事件时间戳|

`pv` 表示浏览次数；`UV` 表示指定范围内去重用户数；`buy` 行数称为购买行为次数，不等同于订单数。原始数据没有订单号、金额和件数，项目不计算 GMV 或客单价。

本文按一次完整处理任务的顺序解释代码。Python 片段取自仓库实现；SQL 章节将生成的长语句分段排版，便于理解。

## 2. 数据准备与独立计算基准

### 2.1 导入依赖和统一时间口径

```python
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
```

`csv` 读取逗号分隔文件，`json` 保存事件和报告，`hashlib` 计算文件摘要，`re` 校验运行标识，`time` 用于限速和超时。`Counter` 统计次数，`defaultdict` 按窗口收集事件，`Path` 处理文件路径。`argparse` 提供命令行参数。

`TZ` 固定为 UTC+8，与 Flink 的 Asia/Shanghai 时间口径一致，避免依赖机器默认时区。`BEHAVIORS` 用集合声明允许的行为类型。

### 2.2 统一写出 JSON

对应文件：[project.py](../project.py)，`write_json()`。

```python
def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
```

先将字符串路径转为 `Path`，再创建父目录。`parents=True` 允许创建多层目录，`exist_ok=True` 允许目录已经存在。`ensure_ascii=False` 保留中文，`indent=2` 让结果便于检查，UTF-8 保证文件编码一致。后续的数据质量清单、基准和对账结果都复用这一函数。

### 2.3 单条记录解析

对应文件：[project.py](../project.py)，`parse_row()`。

```python
def parse_row(row):
    if len(row) != 5:
        raise ValueError('expected five fields')
    user, item, category, behavior, ts = row
    event = dict(user_id=int(user), item_id=int(item), category_id=int(category),
                 behavior=behavior.strip(), ts=int(ts))
    if event['behavior'] not in BEHAVIORS or min(event['user_id'], event['item_id'], event['category_id'], event['ts']) < 0:
        raise ValueError('invalid behavior or negative identifier/timestamp')
    return event
```

第一步要求恰好五列；随后把用户、商品、类目和时间戳转为整数，去除行为值两端的空白。整数转换失败会抛出 `ValueError`。行为不在枚举集合内，或者任一数值为负，也会拒绝该行。

函数返回结构统一的字典，后续模块只需处理同一种事件格式。这里检查的是格式和基本数值范围；日期是否属于分析期，在 `prepare()` 中检查。当前实现允许 ID 为 0，不额外假定数据源的 ID 起始值。

### 2.4 全局指标计算

对应文件：[project.py](../project.py)，`aggregate()`。

```python
def aggregate(events):
    counts = Counter(e['behavior'] for e in events)
    users = {e['user_id'] for e in events}
    buyers = {e['user_id'] for e in events if e['behavior'] == 'buy'}
    return dict(total_events=len(events), active_users=len(users), pv=counts['pv'],
                fav=counts['fav'], cart=counts['cart'], buy_events=counts['buy'], buyers=len(buyers))
```

`Counter` 分别累计四类行为次数。集合推导式对用户去重，购买用户集合先筛选 `buy`，再去重。总事件数取列表长度。

例如同一用户出现两次购买：`buy_events=2`，但 `buyers=1`。因此购买行为数、购买用户数不能混用。该函数既用于总体指标，也用于每个 5 分钟窗口的独立基准。

### 2.5 窗口、小时、类目和累计 UV 基准

对应文件：[project.py](../project.py)，`reference()`。

```python
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
```

这段代码构造五组预期结果，不依赖 Flink 的输出。

1. `datetime.fromtimestamp(..., TZ)` 把秒级时间戳转成北京时间。`daily` 按自然日收集事件。
2. `minute // 5 * 5` 将分钟向下取整到 5 的倍数。例如 10:13:42 归入 10:10:00 开始的窗口，秒和微秒归零。
3. 小时和类目统计只累计 `buy`。小时键保留年月日和小时，避免不同日期的同一小时混在一起。类目键转为字符串，便于与 JSON 对齐。
4. 每一天创建独立 `active` 集合，事件按时间排序。一天分成 144 个十分钟区间；`cursor` 只向前移动，将窗口结束前的用户加入集合。
5. `ts < end.timestamp()` 实现右边界不包含：00:10:00 的事件进入下一累计窗口，不计入 00:10:00 结束的窗口。每日 24:00 的输出键会显示次日 00:00，但仍代表前一日累计结果。
6. 只保存有用户的累计窗口；日内集合逐步增长，跨日重新建立。最终为各组整理可按键比较的字典。

总体 UV 直接从全部事件去重得到，不把各窗口 UV 相加。函数保留输入事件次数，不执行去重删除。

### 2.6 文件读取、质量检查与产物生成

对应文件：[project.py](../project.py)，`prepare()`。

```python
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
```

这段函数完成一次样本准备，顺序如下。

1. `limit` 必须为正。初始化有效事件列表、错误计数、范围外计数和重复记录集合。
2. `utf-8-sig` 兼容文件开头的编码标记；`csv.reader` 逐行拆分。`read` 统计已读取行数，所以 `limit=10000` 指原始输入行数，不是保证输出一万条。
3. 调用 `parse_row()`，将时间戳转成日期。无法解析的记录计入 `invalid`；日期不在 2017-11-25 至 2017-12-03 的记录计入 `out_of_range`。
4. 用五个字段组成的元组判断完全重复记录。`seen` 用于统计重复数量，但事件仍追加到列表；当前业务口径是保留输入行为，不是删除重复事件。
5. 按 `ts` 排序，使主验证任务拥有有序输入。乱序影响另用受控实验验证，不把样本排序当成真实数据天然有序。
6. 每行一个 JSON，写入 `events.jsonl`；`separators` 减少多余空格。对同一文本计算 SHA-256，写入 `manifest.json`，用于核对发送文件是否被改动。
7. 调用 `reference()` 生成 `expected.json`，作为后续独立对账依据。

该函数虽然逐行读取，但有效事件全部保存在内存中再排序，因此适用于当前样本。全量数据处理应改用外部排序或分区处理，不能把这段实现描述成无限容量的数据管道。

本次输入 10,000 行，输出 9,997 条；3 条超出日期范围，格式错误与完全重复记录均为 0。

## 3. Kafka 事件回放

### 3.1 运行隔离与主题命名

对应文件：[project.py](../project.py)，`names()`。

```python
def names(run):
    if not re.fullmatch(r'[a-z][a-z0-9_]{0,48}', run):
        raise ValueError('run must match [a-z][a-z0-9_]{0,48}')
    return {key: f'{run}_{key}' for key in ('events', 'overall', 'windows', 'hours', 'categories', 'cumulative')}
```

正则要求运行标识以小写字母开头，后续只能是小写字母、数字或下划线，总长不超过 49 个字符。这样可以避免把任意文本拼进主题名和 SQL。

每个标识对应六个主题：一个 `events` 输入主题，以及 `overall`、`windows`、`hours`、`categories`、`cumulative` 五个结果主题。它们共享批次前缀，使不同处理任务的数据不会混在一起。

### 3.2 完整发送过程

对应文件：[project.py](../project.py)，`replay()`。

```python
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
```

函数的前半段保证输入和批次明确，后半段负责发送与记录确认数量。

1. 延迟导入 Kafka 依赖，使数据准备和标准库测试可以独立运行。`rate` 必须为正。
2. 重新计算事件文件摘要，与清单比较。不一致时直接终止，防止拿旧基准核对新数据。
3. 查询已有主题；只要本批次任一主题已存在，就拒绝发送，避免同一批次被无意追加两遍。它不是断点续传实现。
4. 创建单分区、单副本主题。输入主题采用 `delete`，配置七天和 1GB 的保留阈值；结果主题采用 `compact`，按消息键压缩旧版本。压缩异步进行，不能假设读取时只剩每个键的一条消息。
5. `acks='all'` 等待当前同步副本确认；当前只有一个副本，不能据此宣称具备多副本容灾。`enable_idempotence=True` 降低生产者重试造成的重复，不等于整个业务流程具备端到端 exactly-once。
6. 每条 JSON 通过序列化器编码为字节，`send(...).get(timeout=30)` 等待确认后才增加 `sent`。
7. 用单调时钟计算本条耗时，再休眠补足 `1/rate`。因此 rate 是目标发送上限，网络慢时实际速度会更低。
8. `finally` 关闭生产者。全部发送完成后，写入包含批次、确认条数和主题映射的回执。

主任务确认发送 9,997 条。同步逐条等待确认有利于解释和核验，但不是最大吞吐量的发送方案。

## 4. Flink SQL 生成与五组指标

### 4.1 SQL 生成器

对应文件：[project.py](../project.py)，`sql()`。

```python
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
```

`names()` 统一主题名，地址正则限制可拼入 SQL 的字符。内部 `sink()` 函数复用结果表模板；`metrics` 定义结果列，`expr` 定义对应聚合表达式，两者顺序必须一致。

读取模式分三种：默认 `latest-offset` 在有界读取初始化时固定结束位置，适用于数据已经发送完的主任务；`specific-offsets` 明确结束 offset，适用于任务边消费边接收的实验；`--live` 不设置结束位置，持续消费。`--live` 与固定结束 offset 不能同时使用。

水位线容忍度限制在 0 到 86400 秒，使用 `divmod` 拆成小时、分钟、秒，再写成 `INTERVAL 'HH:MM:SS' HOUR TO SECOND`，避免将 1200 直接写进默认秒字段时遇到精度限制。

生成器设置时区和并行度，创建一张源表、五张结果表，再把五条 INSERT 放入同一个 Statement Set 提交。Statement Set 将多条写入作为一个作业规划，但不代表五个结果主题具备跨主题事务原子性。

`sql/analysis.sql` 是实测任务使用的 SQL；下面逐段展开其中的计算逻辑。

### 4.2 源表、事件时间和水位线

```sql
SET 'parallelism.default' = '1';
SET 'table.local-time-zone' = 'Asia/Shanghai';
CREATE TABLE events (
  user_id BIGINT, item_id BIGINT, category_id BIGINT,
  behavior STRING, ts BIGINT,
  event_time AS TO_TIMESTAMP_LTZ(ts, 0),
  WATERMARK FOR event_time AS event_time - INTERVAL '00:00:05' HOUR TO SECOND
) WITH (
  'connector' = 'kafka',
  'topic' = 'tb_20261026_105757_events',
  'properties.bootstrap.servers' = '192.168.121.134:9092',
  'properties.group.id' = 'tb_20261026_105757_flink',
  'scan.startup.mode' = 'earliest-offset',
  'scan.bounded.mode' = 'latest-offset',
  'format' = 'json'
);
```

`BIGINT` 存放整数 ID 和时间戳。`event_time AS ...` 是计算列，不需要生产者额外发送。`TO_TIMESTAMP_LTZ(ts, 0)` 中 0 表示输入时间戳精度为秒，不能误当成毫秒。

`DESCRIPTOR(event_time)` 所使用的事件时间来自用户行为本身，而不是发送或处理时刻。水位线描述对事件时间进度的判断；这里留出 5 秒容忍度。它不是让每条数据固定等待 5 秒，也不以电脑墙上时钟为依据。

`earliest-offset` 从保留数据的起始位置读取；与有界结束位置搭配后，可以对完整批次得到确定的最终结果。

### 4.3 Upsert 结果表与主键

```sql
CREATE TABLE categories (
  category_id BIGINT,
  buy_events BIGINT,
  PRIMARY KEY (category_id) NOT ENFORCED
) WITH (
  'connector' = 'upsert-kafka',
  'topic' = 'tb_20261026_105757_categories',
  'properties.bootstrap.servers' = '192.168.121.134:9092',
  'key.format' = 'json',
  'value.format' = 'json'
);
```

以类目表为例，主键是 `category_id`。同一类目的购买次数从 4 变为 5，输出的是该主键的新状态；消费方应该把 4 替换成 5，而不是将两条结果相加。

`NOT ENFORCED` 表示引擎使用主键信息但不执行关系数据库式的唯一约束检查，正确性由聚合分组和写出逻辑保证。其他四张表使用同一连接器模板：

|结果表|主键|值|
|---|---|---|
|overall|metric_key，固定为 all|七个总体指标|
|windows|window_start|窗口内七个指标|
|hours|hour_start|该小时购买次数|
|categories|category_id|类目购买次数|
|cumulative|window_end|当日累计 UV|

窗口主键保留完整日期时间，因此不会把不同日期的 10:00 合并。

### 4.4 总体行为指标

```sql
INSERT INTO overall
SELECT 'all', COUNT(*), COUNT(DISTINCT user_id),
       SUM(CASE WHEN behavior='pv' THEN 1 ELSE 0 END),
       SUM(CASE WHEN behavior='fav' THEN 1 ELSE 0 END),
       SUM(CASE WHEN behavior='cart' THEN 1 ELSE 0 END),
       SUM(CASE WHEN behavior='buy' THEN 1 ELSE 0 END),
       COUNT(DISTINCT CASE WHEN behavior='buy' THEN user_id END)
FROM events;
```

`COUNT(*)` 统计事件，`COUNT(DISTINCT user_id)` 统计用户。四个条件求和分别计算行为次数。最后的 CASE 只对购买事件返回 user_id，其他情况返回 NULL；COUNT 忽略 NULL，再通过 DISTINCT 去重，得到购买人数。常量 all 给全局聚合提供稳定主键。

### 4.5 五分钟滚动窗口

```sql
FROM TABLE(
  TUMBLE(TABLE events, DESCRIPTOR(event_time), INTERVAL '5' MINUTE)
)
GROUP BY window_start, window_end;
```

这是窗口 INSERT 的来源和分组部分；SELECT 复用上一节的七项聚合，并用 `DATE_FORMAT(window_start,'yyyy-MM-dd HH:mm:ss')` 写出窗口键。

`TUMBLE` 将时间划分为互不重叠的五分钟区间。00:00:00 属于 [00:00,00:05)，00:05:00 属于下一个区间。每条事件只进入一个这样的窗口。水位线推进到窗口结束后，该窗口可输出最终聚合；随后才到达且属于已经关闭窗口的事件会影响窗口完整性。

### 4.6 每小时购买次数

```sql
INSERT INTO hours
SELECT DATE_FORMAT(window_start,'yyyy-MM-dd HH:mm:ss'), COUNT(*)
FROM TABLE(TUMBLE(TABLE events, DESCRIPTOR(event_time), INTERVAL '1' HOUR))
WHERE behavior='buy'
GROUP BY window_start, window_end;
```

先按事件时间划分小时，再只保留购买行为并计数。没有购买行为的小时不会自动生成零值记录；若展示完整 24 小时曲线，需要补齐时间维度，不能把缺少结果键直接当作数据丢失。

### 4.7 类目购买次数

```sql
INSERT INTO categories
SELECT category_id, COUNT(*)
FROM events
WHERE behavior='buy'
GROUP BY category_id;
```

这条聚合没有时间窗口，表示当前输入范围内各类目的购买行为总数。SQL 输出全部类目，前端按次数降序取前十展示。它不是只存 Top 10，因此仍能核对全部 131 个购买类目。

### 4.8 每十分钟的当日累计 UV

```sql
INSERT INTO cumulative
SELECT DATE_FORMAT(window_end,'yyyy-MM-dd HH:mm:ss'), COUNT(DISTINCT user_id)
FROM TABLE(CUMULATE(
  TABLE events, DESCRIPTOR(event_time),
  INTERVAL '10' MINUTE, INTERVAL '1' DAY
))
GROUP BY window_start, window_end;
```

`CUMULATE` 的第三个参数是增长步长，第四个是最大窗口长度。窗口形如 [00:00,00:10)、[00:00,00:20)，一直到一天结束；这些窗口起点相同，终点逐步增长。

同一个用户可能出现在多个累计窗口，但每个窗口内部只计一次。当天累计值可以增长或保持，跨天则从新的集合计算。不能把这些累计值相加得到用户总数。

### 4.9 SQL 文件之间的关系

`analysis.sql` 保存五组指标的完整样本任务。`late_20261026_c_short.sql` 与 `late_20261026_c_wide.sql` 使用同样的五组 INSERT，区别在批次主题、水位线容忍度和固定结束 offset=4。

`stream_validation.sql` 保存边发送边消费的四组指标验证语句，结束 offset=9997，尚不含累计 UV。它用于记录这一种读取方式，完整五组结果以 `analysis.sql` 和 `reports/result.json` 为准。

指定 offset 是 Kafka 分区位置，不是通用的数据条数；这里之所以可用 9997 和 4，是因为使用新建单分区主题、从 0 起始且输入非事务消息。多分区或事务输入不能直接套用。

## 5. 作业完成与结果对账

### 5.1 等待计算真正结束

```python
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
```

命令行提供作业 ID，脚本请求 Flink REST 的 jobs 接口并检查 state。FINISHED 时保存完整作业信息；FAILED、CANCELED、SUSPENDED 时以错误结束。每轮间隔两秒，最多 150 轮，但网络请求时间也计入实际耗时，因此五分钟是近似值。

等待结束后才固定结果主题的结束 offset，避免在计算尚未完成时把中间状态误判成最终结果。超时不会自动取消作业，错误信息如实说明这一点。

### 5.2 按主键还原结果并比较

对应文件：[project.py](../project.py)，`collect()`。

```python
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
```

这段代码分为消费、状态还原、结构规范化和比较四部分。

1. 显式分配五个结果分区，不依赖消费组自动分配。查询保留数据的起始 offset 后 seek，再记录每个分区的结束 offset。
2. 循环读取，直到所有分区的位置达到固定结束位置；超过 90 秒则报错。poll 返回的消息如果超过截取边界，不纳入此次快照。
3. 从消息 key 的 JSON 取主键。value 为 NULL 的消息表示删除，调用 pop；非空值覆盖同一主键此前的状态。这样得到的是最终表，而不是更新日志行数。
4. 将结果转换成与 Python 基准相同的字典结构：总体/窗口保留七个字段，小时/类目只取购买次数，累计只取 uv。
5. 每组使用字典相等比较，比较的是所有键及其值，不仅是总数。`all(checks.values())` 要求每组都通过。
6. 报告同时保存批次、检查项、实际结果和数据清单；失败也会写报告，然后返回退出码 1，便于定位差异。

主任务的五项 checks 均为 true。短水位线实验有意产生窗口差异，另用实验汇总验证这一预期。

### 5.3 命令入口与参数分发

对应文件：[project.py](../project.py)，`main()`。

```python
def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare'); p.add_argument('--csv',required=True); p.add_argument('--limit',type=int,default=10000); p.add_argument('--out',default='data/sample')
    p.set_defaults(function=prepare)
    p = sub.add_parser('replay'); p.add_argument('--data',default='data/sample'); p.add_argument('--run',required=True); p.add_argument('--rate',type=float,default=100); p.add_argument('--bootstrap',default='192.168.121.134:9092'); p.set_defaults(function=replay)
    p = sub.add_parser('sql'); p.add_argument('--run',required=True); p.add_argument('--bootstrap',default='192.168.121.134:9092'); p.add_argument('--out',default='sql/analysis.sql'); p.add_argument('--live',action='store_true'); p.add_argument('--end-offset',type=int); p.add_argument('--watermark-seconds',type=int,default=5); p.set_defaults(function=sql)
    p = sub.add_parser('collect'); p.add_argument('--run',required=True); p.add_argument('--data',default='data/sample'); p.add_argument('--out',default='reports/result.json'); p.add_argument('--bootstrap',default='192.168.121.134:9092'); p.set_defaults(function=collect)
    args=parser.parse_args(); args.function(args)
```

四个子命令分别绑定 `prepare`、`replay`、`sql`、`collect`。`set_defaults(function=...)` 把选中的处理函数存入参数对象，最后 `args.function(args)` 调用它。

`required=True` 要求明确选择步骤；整数、浮点数和布尔标记分别由 argparse 转换。文件结尾的 `if __name__ == '__main__': main()` 只在作为脚本执行时进入命令行流程，被测试或实验模块 import 时不会直接执行任务。

## 6. 迟到事件对照实验

### 6.1 读取任务状态

对应文件：[experiments.py](../experiments.py)，`status()`。

```python
def status(job):
    with urllib.request.urlopen(f'http://192.168.121.135:8081/jobs/{job}', timeout=10) as response:
        return json.load(response)['state']
```

使用 Flink REST 接口查询指定作业，网络超时设置为十秒，返回 JSON 中的 state。实验需要先确认任务处于 RUNNING，才开始按计划发送四条记录。

### 6.2 单组实验全过程

对应文件：[experiments.py](../experiments.py)，`trial()`。

```python
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
```

每组实验使用独立主题，避免合成事件混入主任务。

1. 创建主题后，用 1511539200 表示北京时间 2017-11-25 00:00。四条记录的用户分别为 1、2、3、4。
2. 事件顺序为 00:00 buy、00:11 pv、00:01 buy、00:21 pv。第三条故意比第二条更早发生，但更晚发送。
3. `reference()` 不受输入顺序影响，生成完整四条记录的基准。SQL 指定结束 offset=4，使作业在本次输入结束后完成。
4. 使用 scp 传递 SQL，SSH 调用 Flink SQL Client，并从输出提取 32 位作业 ID。子进程返回成功不保证 SQL 成功，因此还要检查是否提取到 Job ID。
5. 等待 RUNNING 后，每条消息确认发送并间隔三秒，让周期性水位线有机会推进。四条发送完毕后等待 FINISHED。
6. 调用 collect。只对表示对账不一致的退出码 1 继续分析，其他异常仍抛出；不会把网络或读取故障直接当成预期迟到结果。
7. 从报告中汇总总事件数、五分钟窗口事件数和窗口购买数，用于两组对照。

实验结果受实际水位线推进影响，因此使用真实作业执行而不是仅凭 SQL 推断。

```python
if __name__=='__main__':
    prefix=sys.argv[1] if len(sys.argv)>1 else 'late_'+time.strftime('%Y%m%d_%H%M%S')
    results=[trial(prefix+'_short',5),trial(prefix+'_wide',1200)]
    report=dict(experiment='same four events, different watermark tolerance',results=results,
                verified=(results[0]['window_events']==3 and results[1]['window_events']==4))
    project.write_json('reports/late_experiment.json',report)
    print(json.dumps(report,indent=2),flush=True)
    if not report['verified']: raise SystemExit('Observed late-event outcome differs; inspect timing')
```

入口分别调用 5 秒与 1200 秒两组容忍度；`verified` 检查五分钟窗口事件数是否分别为 3 和 4，并保存实测作业 ID。该布尔值验证的是预期窗口差异，其他指标保存在结果中，不应把它解释成所有业务指标都做了额外断言。

|容忍度|总体事件数|五分钟窗口事件数|窗口购买次数|
|---|---:|---:|---:|
|5 秒|4|3|1|
|20 分钟|4|4|2|

短水位线下，第三条购买对应的五分钟窗口已经关闭；一小时窗口仍未关闭，因此小时购买指标可以完整。更宽容忍度保留了该事件，但也延后窗口完成时间。这个实验体现了结果完整性与输出时效的取舍。

## 7. 看板后端与前端

### 7.1 后端依赖、参数及离线导出

```python
"""Read-only dashboard: snapshot HTML export or live Kafka result display."""
import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from project import names


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', default='reports/result.json')
    parser.add_argument('--export', help='Export standalone HTML instead of starting a server')
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--run')
    parser.add_argument('--bootstrap', default='192.168.121.134:9092')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8090)
    args = parser.parse_args()
    template = Path(__file__).with_name('dashboard.html').read_text(encoding='utf-8')
    report = json.loads(Path(args.report).read_text(encoding='utf-8')) if Path(args.report).exists() else {}
    if args.export:
        content = template.replace('/*REPORT*/null', json.dumps(report, ensure_ascii=False).replace('<', '\\u003c'))
        Path(args.export).parent.mkdir(parents=True, exist_ok=True)
        Path(args.export).write_text(content, encoding='utf-8')
        return
```

`threading` 支持后台消费和共享状态锁，HTTP 标准库提供页面与 JSON 接口。参数区分报告快照、离线导出和实时消费模式。

模板相对脚本定位，不依赖当前工作目录。`--export` 将报告嵌入模板中的 `/*REPORT*/null`，并将小于号转义，避免嵌入的文本提前结束 script 标签。导出后直接 return，因此离线 HTML 无需连接 Kafka 或运行 HTTP 服务。

### 7.2 实时状态维护

```python
state = dict(report)
    lock = threading.Lock()
    if args.live:
        if not args.run:
            parser.error('--live requires --run')
        state = dict(run=args.run, source='Kafka result topics (live, not reconciled)',
                     actual=dict(overall={},windows={},hours={},categories={},cumulative={}), passed=None)

        def watch():
            from kafka import KafkaConsumer
            topics = names(args.run)
            mapping = {topics[k]: k for k in ('overall','windows','hours','categories','cumulative')}
            fields = dict(overall='metric_key',windows='window_start',hours='hour_start',categories='category_id',cumulative='window_end')
            try:
                consumer = KafkaConsumer(*mapping, bootstrap_servers=args.bootstrap,
                                         auto_offset_reset='earliest', enable_auto_commit=False,
                                         value_deserializer=lambda b: json.loads(b) if b else None,
                                         key_deserializer=lambda b: json.loads(b) if b else None)
                try:
                    for msg in consumer:
                        kind = mapping[msg.topic]
                        key = str(msg.key[fields[kind]])
                        with lock:
                            target = state['actual']
                            if kind == 'overall':
                                target['overall'] = msg.value or {}
                            elif msg.value is None:
                                target[kind].pop(key, None)
                            else:
                                target[kind][key] = msg.value if kind == 'windows' else msg.value['uv' if kind == 'cumulative' else 'buy_events']
                            state['last_update'] = time.strftime('%Y-%m-%d %H:%M:%S')
                finally:
                    consumer.close()
            except Exception as exc:
                with lock:
                    state['error'] = str(exc)
        threading.Thread(target=watch, daemon=True).start()
```

实时模式要求 run，初始化五组空结果，并把 passed 设为 None，表示尚未做最终对账。后台线程读取对应主题，依据主键覆盖旧值或删除 tombstone 对应的状态。

总体指标直接替换整体对象；窗口保留指标字典；小时、类目和累计只保存数值。`lock` 保证写入状态与 HTTP 读取时不会同时修改同一份数据。发生异常时记录 error，前端可以显示故障而不是继续标记成功。`daemon=True` 使后台线程随主进程退出。

### 7.3 页面和数据接口

```python
class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == '/api':
                with lock:
                    content = json.dumps(state, ensure_ascii=False).encode('utf-8')
                kind='application/json; charset=utf-8'
            elif self.path in ('/', '/index.html'):
                content=template.encode('utf-8'); kind='text/html; charset=utf-8'
            else:
                self.send_error(404); return
            self.send_response(200)
            self.send_header('Content-Type',kind)
            self.send_header('Cache-Control','no-store')
            self.send_header('Content-Length',str(len(content)))
            self.end_headers(); self.wfile.write(content)
        def log_message(self, *args):
            pass
    print(f'http://{args.host}:{args.port}',flush=True)
    ThreadingHTTPServer((args.host,args.port),Handler).serve_forever()


if __name__ == '__main__':
    main()
```

`/api` 返回当前指标 JSON，`/` 与 `/index.html` 返回模板，其余路径返回 404。Content-Type 明确编码，Content-Length 表示响应字节数，no-store 避免浏览器缓存旧指标。`log_message` 不打印逐条访问日志。ThreadingHTTPServer 处理浏览器请求；该服务是只读展示，不执行数据计算或数据库写入。

### 7.4 页面结构与样式

对应文件：[dashboard.html](../dashboard.html)。页面结构按分析问题组织：标题和批次信息 → 对账状态 → 四张指标卡片 → 行为分布 → 类目 Top 10 → 按日期选择的小时购买 → 五分钟窗口 → 当日累计 UV。

`cards` 使用四列网格，`grid` 将分析模块排成两列；小屏幕时分别调整为两列和一列。`scroll` 限制长表高度，使窗口结果不会把页面无限拉长。条形图宽度按同一组最大值归一化，比较的是该组内部大小，而不是跨图共享比例。

```javascript
const embedded = /*REPORT*/null;
let last = null;
const el = id => document.getElementById(id);
const fmt = x => Number(x || 0).toLocaleString('zh-CN');
```

`embedded` 由导出器替换为完整报告；在线模式保留 null，通过 API 获取。`last` 保存最近一次渲染的数据。`el` 简化元素查找，`fmt` 添加数字千分位。

### 7.5 前端各函数的职责

|函数|执行过程|作用|
|---|---|---|
|row(parent, values)|创建 tr 和 td，用 textContent 写入每格，再追加到 tbody|避免把数据当成 HTML 执行|
|bars(id, items)|清空旧图，求最大值，为每项创建标签、宽度条和数值|展示四类行为或小时购买分布|
|hourChart()|从 last.actual.hours 中筛选所选日期，按完整时间排序，再调用 bars|切换日期时不需要重新计算 Flink 指标|
|render(r)|更新批次、状态、卡片和五组结果，保留仍有效的日期选择|把统一报告结构转换为可读视图|
|refresh()|请求 /api，检查 HTTP 状态，解析 JSON 并渲染；异常时显示提示|避免请求失败时仍显示成功信息|

`row` 和 `bars` 每次先清空目标区域或构建新行，因此更新界面不会在旧行后重复堆积。

```javascript
Object.entries(a.categories || {})
  .sort((x,y) => y[1]-x[1] || x[0].localeCompare(y[0]))
  .slice(0,10);

o.active_users
  ? (100 * o.buyers / o.active_users).toFixed(2) + '%'
  : '—';
```

类目先按次数降序，次数相同时按字符串 ID 排序，再取前十；并列时的 ID 顺序没有业务价值含义。购买用户占比以活跃用户为分母，分母为零时显示横线，不制造无穷大或伪造的百分比。

`render` 将 passed=true 显示为五组对账通过，false 显示差异，None 显示尚未最终对账。窗口和累计结果按日期时间排序，格式统一后字符串排序与时间先后顺序一致。小时选择框从结果键提取日期，再调用 hourChart。

页面末尾将选择框 onchange 绑定到 hourChart；有 embedded 时直接渲染快照，否则立即 refresh 并每三秒刷新。这三秒是看板请求周期，不是端到端数据处理延迟承诺。

## 8. 一次完整任务的组织

```bash
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
```

脚本将前面各模块连接成一次完整执行，前置条件是 Kafka、Flink 和节点间 SSH 已就绪。

1. `set -euo pipefail` 遇到失败、未定义变量或管道失败时退出，避免继续生成看似成功的报告。
2. 根据脚本所在位置切换到项目根目录，允许从不同目录调用。`${变量:-默认值}` 接受显式参数覆盖；默认取一万行、目标速率 200 条/秒，并生成批次名。
3. 依次调用 prepare、replay、sql。这里先完成数据发送，再提交有界任务，所以主验证侧重完整批次核对；流式消费机制另外通过边发送边消费和迟到实验验证。
4. 将 SQL 传到计算节点，明确 JAVA_HOME，通过 SQL Client 提交，并保存提交输出。
5. 正则提取 Job ID；提取失败就展示日志并退出，不把命令返回当作作业成功。
6. 等待作业完成，再收集结果、逐项对账，最后导出 HTML。任一必要步骤失败都会阻止后续完成提示。

`scripts/start_dashboard.sh` 是展示入口：创建日志目录，检查已记录 PID 是否存活，用 nohup 将只读 HTTP 服务放到后台，记录 PID 和访问地址。`kill -0` 仅用于检查进程存在性，不会终止进程。它不启动消息或计算组件，也不修改处理结果。

`requirements.txt` 将 Kafka 客户端固定为 2.2.15；其余 Python 模块使用标准库。`.gitignore` 排除事件文件、虚拟环境、运行日志和安装包，`.gitattributes` 保证脚本使用 LF 换行。报告 JSON 和离线 HTML 则作为验证产物保留。

## 9. 测试代码与验证目标

```python
import argparse
import json
import tempfile
import unittest
from pathlib import Path
import project


class PipelineTests(unittest.TestCase):
    def test_china_midnight_and_window_boundary(self):
        events = [project.parse_row(['1','2','3','pv','1511539199']),
                  project.parse_row(['1','2','3','buy','1511539200'])]
        result = project.reference(events)
        self.assertIn('2017-11-24 23:55:00', result['windows'])
        self.assertIn('2017-11-25 00:00:00', result['windows'])
        self.assertEqual(result['overall']['active_users'],1)
        self.assertEqual(result['overall']['buyers'],1)

    def test_repeated_events_kept_but_users_distinct(self):
        e=project.parse_row(['1','2','3','buy','1511544070'])
        result=project.aggregate([e,e])
        self.assertEqual(result['buy_events'],2)
        self.assertEqual(result['buyers'],1)

    def test_invalid_rows(self):
        for row in (['1'],['1','2','3','bad','1'],['1','2','3','pv','-1']):
            with self.assertRaises(ValueError): project.parse_row(row)

    def test_prepare_counts_bad_dates_and_sorts(self):
        with tempfile.TemporaryDirectory() as d:
            src=Path(d)/'input.csv'
            src.write_text('1,2,3,buy,1511544070\n1,2,3,pv,1511539200\n1,2,3,pv,1\nbad\n',encoding='utf-8')
            project.prepare(argparse.Namespace(csv=str(src),limit=4,out=d))
            m=json.loads((Path(d)/'manifest.json').read_text())
            self.assertEqual((m['accepted_rows'],m['invalid_rows'],m['out_of_range_rows']),(2,1,1))
            e=[json.loads(x) for x in (Path(d)/'events.jsonl').read_text().splitlines()]
            self.assertLess(e[0]['ts'],e[1]['ts'])

    def test_cumulative_resets_daily_and_excludes_end_boundary(self):
        events = [dict(user_id=u,item_id=1,category_id=1,behavior='pv',ts=t)
                  for u,t in [(1,1511539200),(2,1511539800),(3,1511625600)]]
        c = project.reference(events)['cumulative']
        self.assertEqual(c['2017-11-25 00:10:00'],1)
        self.assertEqual(c['2017-11-25 00:20:00'],2)
        self.assertEqual(c['2017-11-26 00:00:00'],2)
        self.assertEqual(c['2017-11-26 00:10:00'],1)

    def test_run_rejects_sql_injection(self):
        with self.assertRaises(ValueError): project.names("x'; DROP TABLE events;")


if __name__=='__main__': unittest.main()
```

测试使用 unittest，临时文件由 TemporaryDirectory 管理，不接触原始 CSV。

|测试|覆盖的问题|
|---|---|
|test_china_midnight_and_window_boundary|跨北京时间午夜时，事件归入正确日期及五分钟窗口|
|test_repeated_events_kept_but_users_distinct|重复购买行计两次行为，但同一购买用户只计一次|
|test_invalid_rows|列数错误、非法行为及负数输入被拒绝|
|test_prepare_counts_bad_dates_and_sorts|格式错误与范围外日期分开统计，合格事件按时间排序|
|test_cumulative_resets_daily_and_excludes_end_boundary|累计窗口排除右边界，跨日用户集合重置|
|test_run_rejects_sql_injection|带引号和 SQL 片段的运行名无法进入生成流程|

六项单元测试全部通过。单元测试验证局部规则；真实 Kafka/Flink 任务和五组对账验证组件组合后的结果，两类验证不能互相替代。

## 10. 处理结果与项目价值

|结果|实测值|
|---|---:|
|原始样本行数|10,000|
|有效事件数|9,997|
|活跃用户|92|
|浏览次数|8,983|
|收藏次数|298|
|加购次数|537|
|购买行为次数|179|
|购买用户|55|
|非空五分钟窗口|1,825|
|有购买记录的小时|95|
|有购买记录的类目|131|
|累计 UV 窗口|1,296|

项目完成了事件口径统一、消息确认发送、时间窗口计算、更新日志还原、流式结果与独立基准对账，以及分析展示。迟到实验进一步解释了为什么“全局总量正确”不代表“每个窗口都完整”。业务解读见 [样本分析报告](ANALYSIS.md)，计算证据见 [对账结果](../reports/result.json) 和 [迟到实验结果](../reports/late_experiment.json)。

项目经历可以概括为：基于 Kafka 与 Flink SQL 构建淘宝用户行为分析流程，完成五类指标聚合和轻量可视化；设计独立 Python 基准对账与受控迟到实验，在 9,997 条有效事件上验证计算一致性，分析水位线设置对窗口完整性的影响。

这里的结果来自历史数据回放和顺序截取样本，不是生产实时接入，也没有完成一亿条全量验证。购买占比不能直接当成漏斗转化率，样本结论不外推总体。单节点部署、内存排序和持续 distinct 状态的容量边界是后续工程扩展方向。

参考项目：[TurboWay / UserBehaviorFromTaobao_Stream](https://github.com/TurboWay/bigdata_analyse/tree/main/UserBehaviorFromTaobao_Stream)。本项目采用 Kafka KRaft、Flink 1.17.2 与 Python 看板，未部署原方案中的 MySQL 类目维表、Elasticsearch 和 Kibana；新增内容包括输入摘要、运行隔离、五组独立对账、每日累计 UV 和迟到对照验证。
