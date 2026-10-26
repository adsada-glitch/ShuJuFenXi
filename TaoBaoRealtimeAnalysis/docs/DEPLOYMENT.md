# 部署与重启

本项目是在已有环境上增量部署，不会格式化 Kafka/HDFS，不覆盖已有 Hive 表。

|机器|职责|版本/配置|
|---|---|---|
|hadoop101 / 192.168.121.134|Kafka、Python 发送/对账、看板|Kafka 3.7.2，堆 256–512MB；Python 3.11.5|
|hadoop102 / 192.168.121.135|Flink standalone|Flink 1.17.2；JM 1024MB，TM 1536MB；1 slot|

102 的 lib 中需要 `flink-sql-connector-kafka-1.17.2.jar`，当前已安装。Java 路径 `/export/servers/jdk`。项目 Python 依赖固定在 requirements.txt。此版本组合用于现有 Java 8 学习环境，不代表新生产部署推荐。

## 从 Windows 复制代码

把本项目目录复制到 101 的 `/export/taobao-realtime`。`data` 不上传 GitHub；虚拟机上从 `/mnt/taobao/UserBehavior.csv` 生成。使用现有虚拟环境：

```bash
cd /export/taobao-realtime
/export/taobao-stream/.venv/bin/python -m pip install -r requirements.txt
```

需要重新创建环境时：

```bash
/home/ls/anaconda3/bin/python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

随后运行脚本时设置 `PYTHON=/export/taobao-realtime/.venv/bin/python`。

## 关机后恢复

101（确认服务没有运行后再启动，不重复启动）：

```bash
cd /export/servers/kafka_2.12-3.7.2
KAFKA_HEAP_OPTS='-Xms256m -Xmx512m' bin/kafka-server-start.sh -daemon config/kraft/taobao.properties
bin/kafka-topics.sh --bootstrap-server 192.168.121.134:9092 --list
```

102：

```bash
cd /export/servers/flink-1.17.2
JAVA_HOME=/export/servers/jdk bin/start-cluster.sh
curl -s http://192.168.121.135:8081/overview
```

无需启动 Hadoop/Hive/YARN。先确认 1 个空闲 slot；如果还有旧查询，去 Flink 页面核对后取消自己不用的查询。不要盲目终止其他任务。

## 完整重跑

在 101 执行（101 需能免密 ssh 到 102）：

```bash
cd /export/taobao-realtime
bash scripts/run_demo.sh
```

脚本：抽取前 10000 行 → 北京时间日期过滤 → 时间排序 → 新运行主题 → 回放 → 有界 Flink 计算 → 等待 FINISHED → 五组结果对账 → 导出 HTML。每次自动创建新运行标识，拒绝复用主题。它不会自动删除旧主题；样本数据主题保留 7 天，结果主题使用 compaction，长期反复实验应按明确的运行标识手动清理旧主题。

这里只用小样本。prepare 在内存中排序；不要直接把 LIMIT 改成一亿，需要改成外部排序或分区预处理。截止 offset 使用非事务单分区输入且从 0 开始，若改成事务生产/多分区，不能直接用条数当 offset。

## 实时模式

生成 SQL 时使用 `--live`，去掉结束 offset。为了先提交任务再发送，需先创建该 run 的全部主题；当前 replay 将创建主题与发送绑定，最简单方式是在一个终端启动低速 replay，主题创建后立即在另一个终端生成并提交 live SQL。earliest-offset 会补读已发送记录。

```bash
python project.py sql --run 新的运行标识 --live --out sql/live.sql
```

上述“新的运行标识”应替换为 replay 实际使用的值，不能原样执行。提交方法同 run_demo.sh。live 作业不会自动退出；原始事件时间停止推进时，最后一个窗口不会立即结束。不要用伪造的购买事件冲刷窗口。

查看实时结果：

```bash
python dashboard.py --live --run 实际运行标识 --host 192.168.121.134 --port 8090
```

看板每 3 秒刷新，服务只读取结果，不负责计算。默认 `--host` 是 127.0.0.1；显式绑定 101 私网地址后可由 Windows 打开。不要把无认证的实验端口暴露到公网。快照模式不需要 Kafka：`python dashboard.py --report reports/result.json`，或直接双击 reports/dashboard.html。

## 停止

前台看板 Ctrl+C；后台看板先检查自己的 PID 再停止。102：`bin/stop-cluster.sh`；101：`bin/kafka-server-stop.sh`，确认退出后正常关机。不要再次执行 kafka-storage format。

## 打开已验证结果与重跑迟到实验

101 上（服务未启动时）：

```bash
cd /export/taobao-realtime
bash scripts/start_dashboard.sh
```

Windows 浏览器打开 `http://192.168.121.134:8090`。此入口展示最新对账快照；实时消费模式使用上面的 `--live` 命令。修改模板后需重启看板进程。

```bash
/export/taobao-stream/.venv/bin/python experiments.py
```

实验自动生成时间标识，运行两次合成回放，保存 `reports/late_experiment.json`。短水位线窗口对账 false 是预期现象，以汇总报告 verified 为准。任务结束会释放 Flink slot。
