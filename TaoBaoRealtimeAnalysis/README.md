# 淘宝用户行为实时分析：从回放到可核对结果

基于 TurboWay 的实时分析项目思路，在已有的两台低内存虚拟机上重新实现。重点是指标口径、事件时间、数据质量和流批对账，而不是堆叠组件。

```text
历史 CSV → Python 校验/日期过滤/时间排序 → Kafka 输入主题
                                             ↓
                                        Flink SQL
                                             ↓
                         Kafka upsert 结果主题 → Python 轻量看板
                                             ↓
                           独立 Python 基准逐项对账 → HTML/JSON 报告
```

## 功能

- 数据质量记录：无效字段、范围外日期、重复记录数量；保留原始 CSV。
- 显式北京时间（Asia/Shanghai）；原始秒级时间戳转换为 TIMESTAMP_LTZ。
- 总事件、PV、UV、收藏、加购、购买行为数、购买用户数。
- 5 分钟滚动窗口、每小时购买次数、类目购买排行。
- 每 10 分钟的**当日累计 UV**，按天重置，使用完整日期键。
- 唯一运行主题隔离、防止误重放；消息确认后计数。
- 有界回放验证和持续流模式；原始结果落 Kafka，可导出看板快照。
- Python 单元测试、真实数据对账及迟到事件实验。

## 与原项目的区别

参考：[TurboWay / UserBehaviorFromTaobao_Stream](https://github.com/TurboWay/bigdata_analyse/tree/main/UserBehaviorFromTaobao_Stream)。原项目 Flink 1.10.2 + Kafka + MySQL 维表 + Elasticsearch + Kibana。本项目重新编写 Python 和 Flink 1.17.2 SQL，使用 Kafka KRaft 和轻量看板，避免 4.7GB 虚拟机同时承载 ES/Kibana。

当前类目以原数据匿名 category_id 展示，没有把未知类目虚构成中文名称，也没有部署 MySQL 类目维表。不是原项目全部组件的逐字复刻。新增的重点是可验证的数据处理和指标口径，移除了原生成器的数千线程，修正“本地时间附加 UTC 标记”的风险，并避免跨日期用 HH:mm 做结果主键。

## 文件

|文件|用途|
|---|---|
|project.py|数据准备、限速回放、SQL 生成、结果对账|
|dashboard.py / dashboard.html|实时读取结果或导出离线看板|
|sql/|本次实际执行 SQL|
|scripts/run_demo.sh|完整处理任务入口|
|tests/|时区边界、数据质量、重复记录等测试|
|reports/|实际验证结果与看板|
|docs/CODE_WALKTHROUGH.md|从数据准备到结果展示的完整实现与逐段代码解析|
|docs/ANALYSIS.md|指标解释与样本分析|

依赖安装：`python -m pip install -r requirements.txt`。测试：`python -m unittest discover -s tests -v`。完整实现见 [项目代码解析](docs/CODE_WALKTHROUGH.md)。

## 指标口径

购买次数是 buy 行数，不是订单数、件数或 GMV。购买用户占比 = buyers / active_users；不是已证明的浏览到购买漏斗转化率。窗口 UV 不可直接求和得到全局 UV。所有窗口采用左闭右开区间。当前基准保留完全重复的输入记录，并单独报告其数量；更改去重策略必须同时更改基准和 SQL。

## 数据与局限

数据来源：[阿里天池 UserBehavior](https://tianchi.aliyun.com/dataset/649)。原始 CSV 不放 GitHub。运行样本取前 N 行，不是随机抽样，不能代表淘宝总体，也不能据此提出投放预算建议。

项目是历史数据回放实验，不是淘宝线上数据接入。单 Kafka 节点、单 TaskManager，无高可用。默认有界验证不宣称生产级 exactly-once；新 run 是新的独立实验。持续流的全局 distinct 状态会增长，大数据运行需要状态后端、checkpoint、生命周期和容量设计。扩大数据量之前先评估这些限制。

复现参考已注明；本目录为项目实现代码，不包含第三方数据、安装包、密钥或凭据。

## 已验证结果（2026-10-26）

- 10,000 行输入，9,997 行有效事件；92 位用户，179 次购买行为。
- 五组输出逐项对账通过：总指标、1,825 个非空 5 分钟窗口、95 个购买小时、131 个购买类目、1,296 个累计 UV 窗口。
- 六项单元测试通过；迟到实验验证 5 秒/20 分钟水位线分别保留 3/4 条窗口事件。
- [分析报告](docs/ANALYSIS.md) · [对账 JSON](reports/result.json) · [迟到实验](reports/late_experiment.json)
- [离线看板 HTML](reports/dashboard.html)：下载后用浏览器打开，GitHub 文件预览不会执行看板。
- 已部署环境看板：`http://192.168.121.134:8090`（本机私网地址）。
