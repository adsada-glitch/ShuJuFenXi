# 完整学习过程：从 MovieLens 原始数据到分析结论

这份案例面向想应聘数据分析岗位、已有 Python 和 SQL 基础的人。学习主线是：**明确问题 → 理解数据来源 → 检查与处理数据 → 定义指标 → SQL 汇总 → Python 核对和可视化 → 解释结果 → 形成建议与报告。**

这里不从安装软件开始，也不以训练模型为目标。你需要学会的是：为什么这样分析，这个数字到底代表什么，以及结论有没有超出证据。

## 一、先明确这次分析要帮谁解决什么问题

我们设定一个**模拟的内容编辑任务**：内容团队想了解样本里哪些影片获得较多评分、不同类型的反馈如何，以及怎样形成兼顾评分量和口碑的候选名单。

这不是一家真实平台交付的项目。数据来自公开的历史研究样本，因此建议只能是待进一步验证的内容候选，不能声称已经带来播放、留存或收入增长。

把一个模糊需求拆成四个能回答的问题：

| 分析问题 | 为什么要回答 | 本次用的方法 | 预期交付 |
|---|---|---|---|
| 评分参与随时间怎样变化？ | 区分记录量变化来自人数还是人均提交量 | 完整月份比较、日历天数标准化、人数×人均量分解 | 月度表与趋势图 |
| 评分是否集中在少数影片？ | 理解样本覆盖集中在哪里，哪些影片证据稀薄 | 分组聚合、排序、累计占比、长尾切片 | 集中度指标与分布图 |
| 不同类型的覆盖和评分反馈怎样？ | 比较内容结构，同时处理多标签重复计算 | 类型桥表、等比分摊、两种均值口径 | 类型对照表 |
| 哪些影片值得进入口碑候选名单？ | 避免“只有几条评分的满分片”直接登顶 | 样本量门槛、收缩加权均分、参数敏感性 | 候选榜单与稳定性记录 |

**为什么暂时不用预测模型？** 这些问题首先是对已观测样本的描述与诊断，不是预测未来评分。因此不需要先划分训练集、调参或解释 RMSE。只有当任务改成预测时，才需要另设预测目标与时间验证。

最终作品要能展示三件事：你定义了正确的指标；你能可靠地算出它们；你能根据证据提出有边界的建议。

## 二、数据从哪里来，为什么选它

### 2.1 来源和获取方式

数据使用 **MovieLens 100K 固定版本**：

- [官方介绍](https://grouplens.org/datasets/movielens/100k/)
- [原始压缩包](https://files.grouplens.org/datasets/movielens/ml-100k.zip)
- [官方字段说明与许可](https://files.grouplens.org/datasets/movielens/ml-100k-README.txt)

通过官方静态下载获取，不需要爬虫，也不是实时接口。项目下载后检查固定 SHA-256，确保所有人分析的是同一份原包；本地已经下载的包也会核验。

选择它的原因是：有评分明细、电影信息和多标签类型，适合练习事实表与维表关联、指标定义、分组分析和结果解释。规模为 10 万条评分，一般个人电脑可以处理。

选用它的代价也要写清：数据来自 1997–1998 年，本次 UTC 评分时间覆盖 **1997-09-20 至 1998-04-22**；参与者经过筛选，至少有 20 条评分且人口信息完整。它不代表今天所有观众。我们不使用人口信息做群体推断。

### 2.2 先确认一行是什么

| 源文件 | 一行代表什么 | 本次使用哪些字段 |
|---|---|---|
| `u.data` | 某用户对某电影提交的一条评分 | 用户 ID、电影 ID、1–5 星评分、提交时间戳 |
| `u.item` | 一个电影 ID 对应的目录条目 | ID、标题、发行日期、19 个类型标记 |
| `u.genre` | 一个类型编码与名称 | 类型 ID、名称 |

`u.item` 使用 Latin-1 编码，字段以 `|` 分隔。最后 19 列是 0/1 类型标记，一部电影可以同时属于多个类型。按默认逗号分隔或当成“每片只有一种类型”，会把结构读错。

时间戳记录的是**提交评分的时间**，不是观影时间。用户 ID、电影 ID 是类别编码，数值大小没有年龄、质量或发行先后的含义。

### 2.3 先列出它没有提供的东西

没有曝光日志、播放记录、未评分原因、注册时间、付费和收入，所以不能直接计算平台 MAU、真实留存率、播放转化率或收入贡献。

例如“当月有评分的用户数”只代表当月在此样本中提交评分的独立用户；不能把它改名为“平台月活”。这是指标口径问题，不是换一个 SQL 函数就能补齐的数据。

**本节产出：** 用自己的话写一段数据说明，包含来源、粒度、时间、筛选规则，以及至少三个不能回答的业务问题。

## 三、先理解数据关系，再决定怎样清洗

分析用三张主表：

```text
ratings：一条评分一行（用户ID + 电影ID）
    多对一 → movies：一个电影ID一行
                  一对多 → movie_genres：一个电影ID × 一个类型一行
```

评分关联电影信息是多对一；评分继续关联类型是多对多展开，**行数会增加**。能连接成功，不代表连接后的计数仍然正确。

### 3.1 每条清洗规则都要有理由

| 检查 | 防止什么错误 | 处理原则 |
|---|---|---|
| 评分关键字段缺失 | 无法确认用户、电影或评分含义 | 核验来源；关键问题停止流程或隔离，不默默填 0 |
| `(user_id, movie_id)` 重复 | 同一评分组合重复计权 | 先确认是重复导入还是业务允许多次评分；本版本没有该重复 |
| 评分不在 1–5 | 字段解析或取值错误 | 检查解析与源文件；1 星、5 星本身都合法，不作为异常值删掉 |
| 电影 ID 不唯一、评分找不到电影 | 关联倍增或遗漏 | 检查键和外键；不靠 INNER JOIN 把问题藏掉 |
| 标题相同但 ID 不同 | 误删翻拍、版本条目或目录差异 | 保留源 ID 并标记；不能只按标题 `drop_duplicates` |
| 日期缺失、无法解析 | 错误时间分组 | 保留电影，日期转为空并记录；不要因为非关键日期缺失删掉有效评分 |
| 类型未知或多标签 | 丢失未知类、重复计算 | 未知保留，多类型拆桥表，分析时明确计数规则 |
| 不使用的视频发行日、URL 等字段缺失 | 对无关字段过度清洗 | 不对全表一律 `dropna()`；先看这些字段是否影响本次问题 |

**清洗不是必须删掉一些行才算做了工作。** 如果核验后 10 万条评分都有效，正确结果就是保留 10 万条，并留下“为什么可以保留”的证据。

### 3.2 本次原始数据的实际审计

| 检查 | 实际结果 | 处理与理由 |
|---|---|---|
| 评分缺失 / 重复组合 / 越界 | 0 / 0 / 0 | 全部有效，保留 100,000 条 |
| 评分找不到电影 / 找不到用户 | 0 / 0 | 外键完整，不通过关联删记录 |
| 电影 ID 重复 | 0 | 以 ID 为主键保留 1,682 条目录记录 |
| 同名不同 ID | 18 组，涉及 36 行 | 保留并标注；不能无依据按标题合并 |
| 发行日期缺失 / 非空日期解析失败 | 1 / 0 | 缺失保留 NULL，不删电影或关联评分 |
| 视频发行日期缺失 | 1682 | 本次不使用此字段，不造日期 |
| URL 缺失 | 3 | 不影响本次聚合，不据此删行 |
| 多类型 / unknown 类型电影 | 849 / 2 | 按真实标签拆桥表，unknown 保留 |
| 电影类型桥表行数 | 2893 | 与影片数不同，因为一片多标签 |

评分全部保留；电影目录以源 ID 为键保留；缺失或无效的非关键日期单独记录。类型展开只改变关联结构，不改变原始评分事实表。

18 个同名组是需要继续核查的质量问题，不是保留后就自动解决了。本次统计对象是源电影 ID 对应的目录条目，并非人工核实后的唯一作品；如果同一作品确有重复 ID，分散的评分会影响样本量和榜单。进入实际业务前应结合外部标识核实合并规则，当前不凭标题自行合并。

**本节要想明白：** 关键字段为空和不参与分析的字段为空，为什么不能使用同一套删除规则？

## 四、SQL 和 Python 在这条流程里分别做什么

SQL 适合关系关联、分组汇总、去重计数、排名和累计占比；Python 适合读取源文件、数据质量核查、独立复算、画图和敏感性比较。

本例使用 Python 自带的 SQLite 来执行 SQL，不要求你重新安装数据库。你已有的 MySQL 或 SQL Server 也能承载相同表结构和业务逻辑，但日期函数、取前 N 行等语法需要调整。本案例的参考 SQL 方言明确为 SQLite。

### 4.1 进入代码工作区

在 `MovieLensRatingLab` 目录或它的 `notebooks` 目录启动你惯用的 Notebook/IDE。下面的 Python 块按顺序在同一会话执行；`sql` 块用于理解 SQL，也可在连接了本地数据库的客户端执行。

```python
from pathlib import Path
import json
import sqlite3
import sys

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

PROJECT = Path.cwd()
if not (PROJECT / "pyproject.toml").exists():
    PROJECT = PROJECT.parent
assert (PROJECT / "src/rating_lab").is_dir(), "请在项目目录或其 notebooks 目录运行"
sys.path.insert(0, str(PROJECT / "src"))

from rating_lab.analyst import prepare_database, load_queries, run_analysis

database, audit = prepare_database(PROJECT / "data")
conn = sqlite3.connect(database)
queries = load_queries()
OUTPUT = PROJECT / "reports" / "analyst_learning"
OUTPUT.mkdir(parents=True, exist_ok=True)

def query(name):
    return pd.read_sql_query(queries[name], conn)

print(json.dumps(audit, ensure_ascii=False, indent=2))
```

`prepare_database()` 是数据准备实现：核验下载包、按正确编码读取、检查字段与键、解析时间和日期、拆类型、写入本地数据库。第一次先运行它看到审计结果，再打开 [analyst.py](../src/rating_lab/analyst.py) 对照第 3 节逐条找实现，而不是把它当作黑箱清洗。

原包和数据库只存本地 `data/`，不提交 GitHub。你的聚合分析记录存 `reports/analyst_learning/`；自动生成的参考结果存 `reports/analyst/`，两者分开，避免个人练习覆盖参考。

### 4.2 亲手重做关键转换，理解“处理”到底做了什么

下面直接读取已核验的本地原包，重做几个关键转换，不修改数据库。这样可以独立检查数据准备函数，而不是只相信“清洗完成”的提示。

```python
import io
import zipfile

with zipfile.ZipFile(PROJECT / "data/ml-100k.zip") as source:
    raw_ratings = pd.read_csv(io.BytesIO(source.read("ml-100k/u.data")), sep="\t",
                              names=["user_id", "movie_id", "rating", "timestamp"])
    raw_items = pd.read_csv(io.BytesIO(source.read("ml-100k/u.item")), sep="|",
                            encoding="latin-1", header=None, keep_default_na=False)

assert raw_items.shape == (1682, 24)
assert raw_ratings.duplicated(["user_id", "movie_id"]).sum() == 0
assert raw_ratings["rating"].between(1, 5).all()
processed_ratings = raw_ratings.assign(
    rated_at_utc=pd.to_datetime(raw_ratings["timestamp"], unit="s", utc=True),
)
processed_ratings["rating_month"] = processed_ratings["rated_at_utc"].dt.strftime("%Y-%m")
release_dates = pd.to_datetime(raw_items[2], format="%d-%b-%Y", errors="coerce")
assert int(release_dates.isna().sum()) == 1

flags = raw_items.iloc[:, [0] + list(range(5, 24))].copy()
flags.columns = ["movie_id"] + [f"genre_{index}" for index in range(19)]
bridge = flags.melt(id_vars="movie_id", var_name="genre_flag", value_name="present")
bridge = bridge.loc[bridge["present"] == 1].copy()
bridge["genre_id"] = bridge["genre_flag"].str.removeprefix("genre_").astype(int)
assert len(processed_ratings) == 100000
assert len(bridge) == 2893
print({"retained_ratings": len(processed_ratings), "missing_release_dates": int(release_dates.isna().sum()),
       "movie_genre_pairs": len(bridge)})
```

这些操作各有目的：

- 指定分隔符和编码，让字段按源格式进入正确列；不是读入后才凭感觉修数。
- Unix 秒转带 UTC 的时间，再提取月份，让所有 SQL/Python 统计使用同一时区。
- `errors="coerce"` 把缺失/不可解析日期显式变为空值，之后仍要区分原本缺失和非空解析失败；本源后者为 0。
- `melt()` 将 19 列 0/1 标记变成电影与类型的关联行，只保留值为 1 的真实归属，不制造单一“主类型”。
- 保留原包和本地 raw 表，以便追溯；分析使用规范后的表。本次没有删除评分，也没有填造评分和日期。

这段没有保存行级结果，也不应该把 `raw_ratings` 或 `bridge` 的明细作为 GitHub 输出。

### 4.3 用最简单的 SQL 核对事实表

```sql
SELECT COUNT(*) AS rating_count,
       COUNT(DISTINCT user_id) AS scoring_users,
       COUNT(DISTINCT movie_id) AS rated_movies,
       AVG(rating) AS rating_mean
FROM ratings;
```

```python
overview = pd.read_sql_query("""
SELECT COUNT(*) AS rating_count, COUNT(DISTINCT user_id) AS scoring_users,
       COUNT(DISTINCT movie_id) AS rated_movies, AVG(rating) AS rating_mean
FROM ratings
""", conn)
assert tuple(overview.iloc[0][["rating_count", "scoring_users", "rated_movies"]].astype(int)) == (100000, 943, 1682)
print(overview.to_string(index=False))
```

`COUNT(*)` 数的是评分，`COUNT(DISTINCT user_id)` 才数用户；两个数不同不是异常，而是粒度不同。

### 4.4 核对多对一关联是否丢行或倍增

```python
join_audit = pd.read_sql_query("""
SELECT COUNT(*) AS joined_rows,
       SUM(CASE WHEN m.movie_id IS NULL THEN 1 ELSE 0 END) AS unmatched_rows
FROM ratings r LEFT JOIN movies m ON r.movie_id = m.movie_id
""", conn)
assert int(join_audit.iloc[0]["joined_rows"]) == 100000
assert int(join_audit.iloc[0]["unmatched_rows"]) == 0
print(join_audit.to_string(index=False))
```

为什么先 LEFT JOIN？它能保留找不到电影的评分，让关联缺失暴露出来。直接 INNER JOIN 后只看结果，可能把关联失败的记录静默丢掉。

## 五、分析前把指标口径写清楚

| 指标 | 计算方式 | 代表什么与注意点 |
|---|---|---|
| 月评分数 | 该月评分行数 | 样本中的评分提交量，不是播放量 |
| 月评分用户数 | 该月去重用户数 | 提交过评分的人，不是平台 MAU |
| 人均评分数 | 月评分数 ÷ 月评分用户数 | 每个评分参与者的平均提交量 |
| 日均评分数 | 完整月评分数 ÷ 月日历天数 | 控制 28/30/31 天差异；没有记录的日历日也在分母中 |
| Top 10% 评分份额 | 评分最多的前 `ceil(电影数×10%)` 部影片评分数 ÷ 全部评分数 | 描述评分记录集中程度；并列时用 movie_id 固定排序 |
| 高分比例 | 4/5 星评分数 ÷ 该片全部评分数 | 不是全体观众满意度 |
| 类型分摊评分份额 | 该类型分摊权重之和 ÷ 全部评分数 | 多类型影片按 `1/类型数` 分摊，可加总为 100% |
| 收缩加权均分 | `(n×该片均分 + m×全局均分)/(n+m)` | 为低样本均分提供收缩，不是影片真实质量或显著性结论 |

所有阈值先写明再看结果。本例把“长尾”操作性定义为评分数 ≤20 的影片，候选榜要求至少 30 条评分，收缩参考强度 `m=50`；这些是演示选择，不是行业标准或统计保证。

## 六、分析一：月度变化来自参与人数还是人均提交量

### 问题与方法

如果某月评分数下降，你不能立刻断言内容表现下降。至少要拆成：

```text
月评分数 = 当月评分用户数 × 人均评分数
```

再考虑每个月天数不同。这里同时看月总量、人数、人均量和日均量，目的是区分不同来源，而不是只画一条折线就解释为增长或衰退。

SQL 核心是先按月聚合；完整查询在 [analysis.sql](../sql/analysis.sql) 的 `monthly` 段：

```sql
SELECT rating_month,
       COUNT(*) AS rating_count,
       COUNT(DISTINCT user_id) AS scoring_users,
       1.0 * COUNT(*) / COUNT(DISTINCT user_id) AS ratings_per_scoring_user,
       AVG(rating) AS rating_mean
FROM ratings
GROUP BY rating_month
ORDER BY rating_month;
```

### 操作与图表

```python
monthly = query("monthly")
complete_months = monthly[monthly["is_partial_month"] == 0].copy()
assert complete_months["rating_month"].tolist() == ["1997-10", "1997-11", "1997-12", "1998-01", "1998-02", "1998-03"]
print(monthly.to_string(index=False))

fig, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
axes[0].plot(complete_months["rating_month"], complete_months["day_normalized_ratings"], marker="o")
axes[0].set_ylabel("Ratings / calendar day")
axes[1].plot(complete_months["rating_month"], complete_months["scoring_users"], marker="o")
axes[1].set_ylabel("Distinct scoring users")
fig.tight_layout()
fig.savefig(OUTPUT / "monthly_participation.svg", metadata={"Date": None})
plt.show()
```

| 完整月 | 评分数 | 评分用户数 | 人均评分 | 日历日均评分 |
|---|---|---|---|---|
| 1997-10 | 10,304 | 152 | 67.79 | 332.39 |
| 1997-11 | 23,980 | 288 | 83.26 | 799.33 |
| 1997-12 | 11,911 | 184 | 64.73 | 384.23 |
| 1998-01 | 14,095 | 219 | 64.36 | 454.68 |
| 1998-02 | 10,991 | 174 | 63.17 | 392.54 |
| 1998-03 | 12,656 | 226 | 56.00 | 408.26 |

首月 1997-09 和末月 1998-04 只覆盖部分日期，不能把它们与完整月直接做增长比较。这里只把中间月份称为观测范围内的完整日历月；即使覆盖整月，也不代表抓到了平台全部行为。

实际观察：1997-10 到 1997-11，月评分数从 10,304 增至 23,980（+132.7%）；评分用户从 152 增至 288（+89.5%），人均量从 67.79 增至 83.26（+22.8%）。人数和人均提交量都参与了记录量的增长；这只是恒等分解，不证明某个原因造成了增长。随后月份也不呈持续单向上升。

另一个需要追问的质量细节：1997-12 有 31 个日历日，但只有 29 天出现评分记录。日历日均仍以 31 为分母；另外两天没有记录，不能证明它们没有用户行为，也可能与采样或记录机制有关。

**如何形成建议：** 如果是在真实团队，先核查数据采集是否变化，再结合曝光、播放和活动日历排查参与变化；仅凭评分日志，不把下降归因于内容质量。这里不计算“用户流失率”：没再评分不等于不再使用平台。

**你的检查：** 任选相邻两个完整月，比较总评分数、人数、人均量、日均量。写一句说明“哪个因素变化更明显”，再写一个替代解释。

## 七、分析二：评分记录有多集中，长尾证据够不够

### 为什么先聚合到一片一行

要研究影片集中度，先把评分明细变成电影级表。若直接把每条评分当一个电影来排名，分析粒度已经错了。

```sql
WITH movie_counts AS (
  SELECT movie_id, COUNT(*) AS rating_count
  FROM ratings GROUP BY movie_id
)
SELECT movie_id, rating_count,
       ROW_NUMBER() OVER (ORDER BY rating_count DESC, movie_id) AS count_rank,
       SUM(rating_count) OVER (
         ORDER BY rating_count DESC, movie_id ROWS UNBOUNDED PRECEDING
       ) * 1.0 / SUM(rating_count) OVER () AS cumulative_share
FROM movie_counts;
```

`ROW_NUMBER` 给每片稳定顺序；窗口累计和把“前若干部影片合计占多少评分”直接算出来。并列规则提前固定为 movie_id，避免阈值附近的结果每次变化。

### 执行并用 Python 独立核对

```python
concentration = query("concentration")
counts = pd.read_sql_query("SELECT movie_id, COUNT(*) AS n FROM ratings GROUP BY movie_id", conn)
top_n = int(np.ceil(len(counts) * 0.10))
python_top = counts.sort_values(["n", "movie_id"], ascending=[False, True]).head(top_n)
python_share = python_top["n"].sum() / counts["n"].sum()
sql_share = float(concentration.iloc[0]["top10_rating_share"])
assert np.isclose(python_share, sql_share)
print(concentration.to_string(index=False))

ordered = np.sort(counts["n"].to_numpy())
x = np.r_[0, np.arange(1, len(ordered) + 1) / len(ordered)]
y = np.r_[0, np.cumsum(ordered) / ordered.sum()]
fig, ax = plt.subplots(figsize=(6, 5))
ax.plot(x, y, label="Observed rating concentration")
ax.plot([0, 1], [0, 1], "--", color="gray", label="Equal counts reference")
ax.set(xlabel="Cumulative share of movies (least rated first)", ylabel="Cumulative share of ratings")
ax.legend()
fig.tight_layout()
fig.savefig(OUTPUT / "concentration.svg", metadata={"Date": None})
plt.show()
```

Python 和 SQL 都使用相同的 `rating_count DESC, movie_id ASC` 顺序；如果要比较具体影片名单，并列规则也必须一致，不能只核对最终百分比。

本次结果：前 10%（向上取整为 **169 部**）影片获得 **42,871 / 100,000 = 42.87%** 的评分；前 20%（337 部）占 **64.72%**。≤20 条评分的电影有 **755 部，占目录影片 44.89%**，但合计只占评分 **5.27%**。

这表示样本中的观测证据分布不均；不是对所有内容都拥有同等可靠的评分估计。

**能解释什么：** 哪些地方观测证据密集、哪些影片只有少量记录。**不能解释什么：** 观看流量分布、市场份额、平台应该给头部多少曝光。

**建议与验证：** 形成候选名单时同时展示评分数；对小样本片不要仅看均分决定资源。若要发现“被低估的长尾”，还需要曝光和播放数据，分清“没人看见”与“看见但不喜欢”。

## 八、分析三：多类型影片怎样比较，才不会重复算

### 先展示连接膨胀，而不是直接画类型排行榜

```python
fanout = pd.read_sql_query("""
SELECT COUNT(*) AS tagged_rating_rows
FROM ratings r JOIN movie_genres g ON r.movie_id = g.movie_id
""", conn)
print(fanout.to_string(index=False))
```

类型关联把 **100,000 条评分**展开成 **212,595 行**。例如一条属于三个标签的影片评分，会出现三次。

这是多标签展开的预期结果，不意味着数据突然多了那么多条独立评分。

### 两种口径回答不同问题

- **全额计数：** 一部三类型电影的每条评分都计入三个类型。适合回答“带这个标签的影片一共获得多少评分”，但各类型计数相加会超过总评分。
- **等比分摊：** 一条三类型电影评分给每个标签 `1/3`。适合描述一份可加总的类型结构。它是明确的记账假设，并不是证明观众的注意力平均分配给三个类型。

等比分摊的核心 SQL：

```sql
WITH genre_count AS (
  SELECT movie_id, COUNT(*) AS k FROM movie_genres GROUP BY movie_id
)
SELECT g.genre,
       SUM(1.0 / k.k) AS weighted_count,
       SUM(r.rating * 1.0 / k.k) / SUM(1.0 / k.k) AS weighted_rating_mean
FROM ratings r
JOIN movie_genres g ON r.movie_id = g.movie_id
JOIN genre_count k ON r.movie_id = k.movie_id
GROUP BY g.genre;
```

### 执行并核对可加总性

```python
genre = query("genre")
assert np.isclose(genre["weighted_count"].sum(), 100000)
assert np.isclose(genre["weighted_share"].sum(), 1.0)
print(genre.sort_values("weighted_share", ascending=False).to_string(index=False))
```

| 类型 | 带该标签的影片数 | 全额关联评分行 | 分摊评分份额 | 分摊加权均分 | 电影等权均分 |
|---|---|---|---|---|---|
| Drama | 725 | 39,895 | 24.61% | 3.683 | 3.187 |
| Comedy | 505 | 29,832 | 18.29% | 3.350 | 3.001 |
| Action | 251 | 25,589 | 9.59% | 3.423 | 2.966 |
| Thriller | 251 | 21,872 | 9.40% | 3.496 | 3.137 |
| Romance | 247 | 19,461 | 8.10% | 3.582 | 3.244 |

上表按分摊评分份额取前五类，不是按最高均分挑选。所有 19 个类型均包含在聚合结果中；unknown 未删除。

这里实际有三种均值，要与输出字段一一对应：

- `rating_mean`：标签内每条评分等权，评分多的影片贡献更大。
- `weighted_rating_mean`：每条评分按 `1/该片类型数` 计权；多类型片在每个标签里贡献更少。
- `equal_movie_weight_mean`：先算每片均分，再在类型内对电影等权，描述样本中“典型一部片”的平均反馈。

它们回答不同问题，数值不一样不代表谁算错。前面表格同时展示分摊均分和电影等权均分，完整聚合表保留三种口径。

**解释边界：** 类型标签互相重叠，用户选择看什么、是否评分也不同。因此类型间均分差异是描述性结果，不能说某类型导致满意度更高。类型独立用户数也不能跨类型相加。

**建议与验证：** 将类型评分结构与实际内容目录、曝光结构对照，找值得调查的差异。若没有曝光和播放分母，不能用评分份额推断供需缺口。

## 九、分析四：高分榜为什么不能只按平均分排序

### 问题在哪里

1 条 5 星评分和 200 条平均 4.3 星评分，虽然前者均分高，但证据量不同。简单按均分排榜容易让低样本极端值占据前列。

本例使用两个明确的分析规则：

1. 候选至少有 30 条评分，减少极低样本条目。
2. 在榜单中同时展示原均分、评分数、4/5 星占比和收缩分，不把一个综合数当作全部证据。

### 为什么用收缩加权均分

```text
收缩分 = (n × 该片均分 + m × 全局评分均值) / (n + m)
```

`n` 是该片评分数，`m` 是我们给全局均分的参考权重。`n` 小时收缩更明显，`n` 大时更接近该片原均分。本例先固定 `m=50`，再用 `20/50/100` 检查结论是否依赖单一选择。

这是收缩估计风格的平滑排序，不是显著性检验、置信区间或电影真实质量。30 条与 `m=50` 都是透明的操作选择，不能包装成经过证明的最佳参数。

SQL 的核心计算是：先按片聚合 `COUNT/AVG`，另算全局均分，再应用上述公式，最后用窗口函数排名。完整 SQL 见 `movie_candidates` 段。

```python
candidates = query("movie_candidates")
top = candidates.sort_values("shrunk_rank").head(10)
print(top[["title", "rating_count", "raw_mean", "high_rating_ratio", "shrunk_mean", "shrunk_rank"]].to_string(index=False))
first = top.iloc[0]
recalculated = (first["rating_count"] * first["raw_mean"] + first["prior_strength"] * first["global_mean"]) / (first["rating_count"] + first["prior_strength"])
assert np.isclose(recalculated, first["shrunk_mean"])
```

| 收缩排名 | 影片 | 评分数 | 原均分 | 收缩分 | 4/5 星比例 |
|---|---|---|---|---|---|
| 1 | Schindler's List (1993) | 298 | 4.466 | 4.332 | 88.9% |
| 2 | Shawshank Redemption, The (1994) | 283 | 4.445 | 4.308 | 90.1% |
| 3 | Casablanca (1942) | 243 | 4.457 | 4.299 | 88.9% |
| 4 | Star Wars (1977) | 583 | 4.358 | 4.293 | 85.9% |
| 5 | Usual Suspects, The (1995) | 267 | 4.386 | 4.251 | 86.9% |

本次共有 806 部影片达到 30 条门槛，全局均分为 3.52986。例如 A Close Shave 的原均分约 4.491、112 条评分，m=50 后约 4.194；Schindler's List 的原均分约 4.466、298 条评分，收缩后约 4.332。排序改变反映样本量与规则的影响，不能由此断言哪部片客观更好。

### 接着检查榜单是否稳定

```python
sensitivity = query("sensitivity")
top_sets = {int(m): set(rows["movie_id"]) for m, rows in sensitivity.groupby("prior_strength")}
overlap_rows = []
for left, right in [(20, 50), (50, 100), (20, 100)]:
    shared = len(top_sets[left] & top_sets[right])
    overlap_rows.append({"left_m": left, "right_m": right,
                         "shared_top20": shared,
                         "jaccard": shared / len(top_sets[left] | top_sets[right])})
print(pd.DataFrame(overlap_rows).to_string(index=False))
```

| 参考强度对比 | Top20 共同影片 | Jaccard（交集/并集） |
|---|---|---|
| 20 vs 50 | 19 / 20 | 90.48% |
| 20 vs 100 | 17 / 20 | 73.91% |
| 50 vs 100 | 18 / 20 | 81.82% |

这是名单集合的交集，不说明共同影片排名顺序相同。m=20 与 m=100 有 17 部共同影片，也意味着有边缘候选会随收缩强度变化。

这检验的是**分析选择的敏感性**，不是独立样本上的验证。名单稳定也不能证明上线有效；不稳定则提醒你：边缘候选不该被当作确定结论。

**本节练习：** 复制 SQL 到本地另做两个版本，把最少评分数从 30 改成 20、50，比较候选集合和排除的影片数。明确记录改了什么；不要在看到最喜欢的电影上榜后才挑一个阈值。

## 十、从结果走到结论，再走到有条件的建议

不要用“发现头部集中，建议优化推荐”这种缺少中间证据的句子。每条结论都按以下顺序写：

```text
现象（数字与分母）
→ 有限解释（数据支持什么）
→ 替代解释（还有什么可能造成这个现象）
→ 行动候选（具体准备尝试什么）
→ 验证计划（要补哪些数据、怎样判断成败）
```

| 实证观察 | 有限解释与替代解释 | 行动候选 | 还需什么验证 |
|---|---|---|---|
| 10→11 月评分用户 152→288，人均 67.79→83.26 | 记录量增长同时伴随人数与人均提交量增加；可能受样本组成和记录方式影响 | 先核查记录范围与参与机制，不直接归因于内容改善 | 活动日历、数据采集变更与曝光/播放日志 |
| 前169部占评分42.87%；755部长尾只占5.27% | 评分证据集中；小样本片的均分更容易波动 | 榜单同时展示量与分，不只按均分决策 | 曝光、观看及评价提交率，区分未被看见与反馈较低 |
| Drama/Comedy 分摊评分份额约24.61%/18.29% | 描述本样本的类型记录结构，不是市场需求；标签和目录构成也会影响份额 | 将评分结构与内容供给、曝光结构一起检查 | 同口径的目录、曝光和播放分母 |
| m20与m100的Top20共同17部 | 部分边缘候选依赖分析规则；名单稳定也不等于上线有效 | 将稳定且量足的对象列为编辑复核候选，记录边缘项 | 内容可用性、业务目标和预设的线上对照实验 |

这些建议并不是“分析出了一个数，所以应该上线”。例如候选榜仅帮助筛出值得编辑复核的对象；是否增加曝光，仍要结合内容可用性、业务目标和实验结果。

若未来确实拿到线上数据，可以预先设计对照实验，衡量曝光后的播放、完播等预定指标，并考虑随机化、实验单位和负向影响。这里没有这些数据，所以不预写提升幅度。

## 十一、把整条过程写成一份分析报告

先用自己的话写 `docs/MY_ANALYSIS.md`，结构如下：

```markdown
# MovieLens 内容评分分析

## 1. 分析背景和问题
模拟谁的需求？四个具体问题是什么？

## 2. 数据来源和分析范围
官方来源、固定版本、粒度、UTC时间范围、用户筛选规则、缺失的业务数据。

## 3. 数据检查与处理
每条规则的理由、实际发现、处理决定、处理前后数量；是否改变评分总数。

## 4. 指标与方法
分子分母、完整月、Top比例与并列规则、多标签分摊、候选门槛、收缩公式。

## 5. 分析结果
每个问题配一张表/图、一条有数字的观察、一条替代解释。

## 6. 结论、建议与验证
把证据和行动候选分开；明确下一步需要哪些数据。

## 7. 限制与复现
样本选择、年代、主动评分、参数敏感性；代码版本、SQL文件和运行方式。
```

完成手动分析后，再运行整条自动流程，对照你的结果：

```python
evidence = {name: json.loads(frame.to_json(orient="records")) for name, frame in {
    "monthly": monthly,
    "concentration": concentration,
    "genre": genre,
    "top30_candidates": candidates.sort_values("shrunk_rank").head(30),
    "sensitivity": sensitivity,
    "top20_overlap": pd.DataFrame(overlap_rows),
}.items()}
(OUTPUT / "evidence.json").write_text(
    json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
)
conn.close()
reference_result = run_analysis(PROJECT / "data", PROJECT / "reports/analyst")
```

先保存自己的聚合证据，再关闭原连接，最后重新运行参考流程；Windows 下不能让旧连接占用着数据库文件时替换它。

自动参考：[分析报告](../reports/analyst/ANALYSIS_REPORT.md)、[聚合指标](../reports/analyst/metrics.json)、[质量审计](../reports/analyst/audit.json)。这些文件方便核对数值，不代替你解释为什么选这些方法。

### 面向求职，怎样讲这个项目

在你实际完成并能复现后，可以这样概括：

> 我用 MovieLens 公开历史数据完成了一个内容评分分析案例。先明确数据粒度和指标边界，审计十万条评分并建立电影维表、类型桥表；用 SQL 做月度参与、集中度和多标签分摊，用 Python 独立核对和可视化；再用样本门槛与收缩排序检查口碑候选的稳定性。结论区分评分行为与观看行为，并给出需要曝光和播放数据才能验证的后续方案。

不要把公开练习说成真实企业项目，也不要写“带来收入增长 X%”。求职作品的说服力来自分析过程可解释、口径可靠和建议有依据。

## 十二、怎样判断你真的学会了

- [ ] 能解释数据来自哪里，为什么选择它，以及它不代表谁。
- [ ] 能说清评分事实表、电影维表、类型桥表的粒度和关联关系。
- [ ] 每项清洗都有理由和数量记录，没有为了展示技巧随意删数据。
- [ ] 不把评分用户数叫平台 MAU，不把评分数叫播放量。
- [ ] 首尾部分月份没有被拿来直接解释增长或衰退。
- [ ] 能用人数与人均提交量拆解月度变化。
- [ ] SQL 集中度结果能用 Python 独立复算。
- [ ] 能解释多标签展开后的行数变化，并核对分摊权重恢复到十万。
- [ ] 能手算收缩分，并说明它为什么不是显著性证据。
- [ ] 改过至少一个样本门槛，记录了榜单和结论的变化。
- [ ] 每条建议都有数字、替代解释、适用范围和验证方式。
- [ ] 能从源包重新生成结果，并用自己的话讲述整条过程。

## 附录：运行和文件入口

主线代码：`src/rating_lab/analyst.py`；完整 SQL：`sql/analysis.sql`；可执行工作区：`notebooks/01_explore.ipynb`。

已能导入 numpy、pandas、matplotlib 时可直接按第 4 节运行。若缺少包，在你当前使用的 Python 环境安装项目依赖：`python -m pip install -e .`。整条参考流程可用 `python -m rating_lab.analyst` 运行；这只是复现方式，不是学习顺序。

SQLite 的日期表达式与 MySQL/SQL Server 不完全相同。例如 SQLite 常用 `strftime`，MySQL 常用 `DATE_FORMAT`；迁移时保持字段粒度、时区、NULL 处理和分母一致，不是只改函数名字。

原来的评分预测代码与基线报告仍作为可选技术扩展保留，不属于这次岗位分析主线。

数据使用 GroupLens 的单独许可，代码许可不覆盖源数据。GitHub 只放代码、原创说明和聚合结果，不提交原包、数据库、行级评分、逐用户输出；Notebook 发布前清空输出。

引用：F. Maxwell Harper and Joseph A. Konstan. 2015. *The MovieLens Datasets: History and Context*. ACM TIIS 5(4), Article 19. [DOI: 10.1145/2827872](https://doi.org/10.1145/2827872).
