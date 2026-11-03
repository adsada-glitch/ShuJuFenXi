# 完整学习过程：用 Python 从原始数据做到分析结论

这份案例全部使用 **Python + pandas + matplotlib**。数据是 pandas 的 DataFrame，也就是内存中的表格；我们逐步读取、检查、关联、分组计算、画图和总结。

**学习顺序：问题 → 数据来源 → 检查与处理 → 指标 → 分析 → 解释 → 建议。**

你可以直接打开 [配套 Notebook](../notebooks/01_explore.ipynb)：本文件的 Python 代码已按顺序放进单元格。每运行一格，看清中间表和检查结果，再进入下一格。所有单元格共享变量，重启内核后应从第一格顺序运行。

## 一、明确分析要解决什么问题

任务是一个模拟的内容编辑案例：理解哪些影片获得较多评分、类型结构怎样，以及怎样形成兼顾评分量与反馈的候选名单。

| 问题 | 为什么分析 | 本次方法 |
|---|---|---|
| 月度评分参与怎样变化？ | 分清评分量变化来自人数还是人均提交量 | `groupby`、去重人数、日均量、人数×人均量分解 |
| 评分集中在少数影片吗？ | 理解证据分布，识别低样本影片 | 聚合、排序、累计占比、长尾切片 |
| 多类型电影怎样比较？ | 避免一部电影多个标签带来的重复计算 | `melt`、`merge`、`1/k` 分摊、多种均值 |
| 哪些电影值得进入口碑候选？ | 避免极少评分的高均分直接登顶 | 样本门槛、收缩加权均分、敏感性比较 |

这些问题是对历史已观测样本的描述和诊断，不要求先训练预测模型。本项目不声称为真实企业创造增长；候选建议也需要后续数据验证。

## 二、数据来源、字段与分析范围

使用固定的 **MovieLens 100K**：

- [官方介绍](https://grouplens.org/datasets/movielens/100k/)
- [原始压缩包](https://files.grouplens.org/datasets/movielens/ml-100k.zip)
- [字段说明和许可](https://files.grouplens.org/datasets/movielens/ml-100k-README.txt)

它有 100,000 条评分、943 位用户、1,682 个电影目录 ID。本次按 UTC 评分时间覆盖 1997-09-20 至 1998-04-22。用户经过筛选，至少有 20 条评分且人口信息完整；本次只使用用户 ID 检查关联，不做人口属性推断。

选择它是因为有评分明细、电影信息和多标签类型，适合练习数据质量、表格关联、分组分析和结果解释。历史年代、用户筛选和主动评分机制都限制了外推。

| 文件 | 一行是什么 | 使用字段 |
|---|---|---|
| `u.data` | 用户对电影提交的一条评分 | user_id、movie_id、rating、timestamp |
| `u.item` | 一个电影 ID 的目录记录 | 标题、发行日期、19 个类型标记 |
| `u.genre` | 一个类型编码 | 类型 ID、名称 |
| `u.user` | 一个入选用户 | 本次仅取用户 ID |

时间戳代表评分提交时间；评分数不是播放量，评分用户数不是平台月活。没有曝光、播放、注册、付费数据，不能直接计算转化、真实留存或收入贡献。

## 三、读取数据：先看到原始表

### 3.1 准备 Python 工作区

在项目目录或 `notebooks` 目录打开 Notebook。这里的 `PROJECT` 表示项目文件夹，`DATA` 放原包，`OUTPUT` 放你自己的聚合结果与图。

```python
from pathlib import Path
import io
import json
import sys
import zipfile

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

PROJECT = Path.cwd()
if not (PROJECT / "pyproject.toml").exists():
    PROJECT = PROJECT.parent
assert (PROJECT / "src/rating_lab").is_dir(), "请在项目目录或 notebooks 目录运行"
sys.path.insert(0, str(PROJECT / "src"))

DATA = PROJECT / "data"
OUTPUT = PROJECT / "reports/analyst_learning"
OUTPUT.mkdir(parents=True, exist_ok=True)
```

### 3.2 获取评分原表

项目已有的 `load_ratings()` 负责获取固定源包、检查 SHA-256，并做基本的行数、重复和评分范围校验。这里再用 `pd.read_csv()` 从已核验的包中重读一遍，让读取过程可见；第 4 节的质量检查是对输入的显式复核。

```python
from rating_lab.data import load_ratings, SOURCE_SHA256

verified_ratings = load_ratings(DATA)
with zipfile.ZipFile(DATA / "ml-100k.zip") as source:
    ratings_raw = pd.read_csv(io.BytesIO(source.read("ml-100k/u.data")), sep="\t",
                              names=["user_id", "movie_id", "rating", "timestamp"])
pd.testing.assert_frame_equal(ratings_raw, verified_ratings)
print("评分原表行列数：", ratings_raw.shape)
print(ratings_raw.dtypes)
ratings_raw.head()
```

预期形状 `(100000, 4)`。一行是一条评分，不能把一行当一位用户或一部电影。`head()` 帮你确认列的含义；ID 是类别标识，不能按数值大小解释高低。

### 3.3 读取电影与类型

`u.item` 用 `|` 分隔、Latin-1 编码；最后 19 列是 0/1 类型标记。我们保留原始空字符串，以便区分“本来缺失”和“解析失败”。

```python
with zipfile.ZipFile(DATA / "ml-100k.zip") as source:
    genres = pd.read_csv(io.BytesIO(source.read("ml-100k/u.genre")), sep="|",
                         names=["genre", "genre_id"], encoding="latin-1")
    flag_columns = [f"genre_{value}" for value in genres.sort_values("genre_id")["genre_id"]]
    raw_movies = pd.read_csv(
        io.BytesIO(source.read("ml-100k/u.item")), sep="|", encoding="latin-1",
        names=["movie_id", "title", "release_date_raw", "video_release_date_raw", "imdb_url"] + flag_columns,
        keep_default_na=False,
    )
    users = pd.read_csv(io.BytesIO(source.read("ml-100k/u.user")), sep="|", header=None,
                        usecols=[0], encoding="latin-1").rename(columns={0: "user_id"})

assert raw_movies.shape == (1682, 24)
assert len(genres) == 19
print("电影原表：", raw_movies.shape, "；类型表：", genres.shape)
raw_movies[["movie_id", "title", "release_date_raw"]].head()
```

为什么指定格式？如果用错分隔符，可能把整行读成一列；编码错误可能使标题损坏。先读对结构，再讨论清洗。

## 四、检查质量，并解释每项处理决定

### 4.1 不是所有缺失或重复都应该删除

| 检查 | 风险 | 处理原则 |
|---|---|---|
| 评分关键字段缺失或越界 | 无法正确计算指标 | 核验来源，关键问题停止或隔离；不默默填 0 |
| 用户电影组合重复 | 同一记录重复计权 | 先确认业务含义；本源该组合没有重复 |
| 电影 ID 重复或关联不到 | 关联倍增、遗漏 | 核对键和来源，让问题显式暴露 |
| 标题相同、ID 不同 | 无依据地合并或误删 | 保留源 ID，并记录待核查项 |
| 发行日期缺失 | 时间分析不完整 | 转为空并记录，保留电影及其有效评分 |
| 无关字段缺失 | 过度清洗损失有效记录 | 不对全表一律 `dropna()` |
| 1 星、5 星 | 被误当作异常值 | 都属于合法评分，保留 |

先把实际检查结果写出来：

```python
quality = {
    "rating_rows": len(ratings_raw),
    "missing_rating_cells": int(ratings_raw.isna().sum().sum()),
    "duplicate_user_movie_pairs": int(ratings_raw.duplicated(["user_id", "movie_id"]).sum()),
    "out_of_range_ratings": int((~ratings_raw["rating"].between(1, 5)).sum()),
    "duplicate_movie_ids": int(raw_movies["movie_id"].duplicated().sum()),
    "duplicate_title_groups": int((raw_movies["title"].value_counts() > 1).sum()),
    "missing_release_dates": int(raw_movies["release_date_raw"].eq("").sum()),
    "missing_video_dates": int(raw_movies["video_release_date_raw"].eq("").sum()),
    "missing_urls": int(raw_movies["imdb_url"].eq("").sum()),
}
assert quality["rating_rows"] == 100000
assert quality["missing_rating_cells"] == quality["duplicate_user_movie_pairs"] == quality["out_of_range_ratings"] == 0
assert quality["duplicate_movie_ids"] == 0
assert ratings_raw["user_id"].isin(users["user_id"]).all()
assert ratings_raw["movie_id"].isin(raw_movies["movie_id"]).all()
print(pd.Series(quality).to_string())
```

### 4.2 实际发现与决策

| 检查 | 实际结果 | 处理与理由 |
|---|---|---|
| 评分缺失 / 重复组合 / 越界 | 0 / 0 / 0 | 全部有效，保留 100,000 条 |
| 评分找不到电影 / 找不到用户 | 0 / 0 | ID 关联完整，不通过关联删记录 |
| 电影 ID 重复 | 0 | 以 ID 为主键保留 1,682 条目录记录 |
| 同名不同 ID | 18 组，涉及 36 行 | 保留并标注；不能无依据按标题合并 |
| 发行日期缺失 / 非空日期解析失败 | 1 / 0 | 缺失保留 NaT，不删电影或关联评分 |
| 视频发行日期缺失 | 1682 | 本次不使用此字段，不造日期 |
| URL 缺失 | 3 | 不影响本次聚合，不据此删行 |
| 多类型 / unknown 类型电影 | 849 / 2 | 按真实标签拆桥表，unknown 保留 |
| 电影类型桥表行数 | 2893 | 与影片数不同，因为一片多标签 |

评分全部保留。18 个同名组仍然是待核查的质量问题；本次按源电影 ID 统计，不代表已经人工确认了唯一作品。实际业务使用前，应结合外部标识核查重复作品及合并规则。

清洗的价值是保证分析含义正确，不是必须删除一些行才算完成。

### 4.3 转换评分时间和发行日期

```python
ratings = ratings_raw.copy()
ratings["rated_at_utc"] = pd.to_datetime(ratings["timestamp"], unit="s", utc=True)
ratings["rating_month"] = ratings["rated_at_utc"].dt.strftime("%Y-%m")

release_dates = pd.to_datetime(raw_movies["release_date_raw"], format="%d-%b-%Y", errors="coerce")
nonempty = raw_movies["release_date_raw"].ne("")
invalid_dates = int((nonempty & release_dates.isna()).sum())
assert invalid_dates == 0
movies = raw_movies[["movie_id", "title"]].copy()
movies["release_date"] = release_dates
movies["release_year"] = release_dates.dt.year.astype("Int64")
assert len(ratings) == 100000 and len(movies) == 1682
print("原本缺日期：", int((~nonempty).sum()), "；非空但解析失败：", invalid_dates)
movies.head()
```

`utc=True` 统一时间口径；`errors="coerce"` 让无法解析的日期变成空值，但还要单独统计“原本缺失”和“非空解析失败”。本源缺日期 1 条、非空解析失败 0 条，不补造日期，也不因此删除评分。

### 4.4 把多个类型标记变成关联表

```python
movie_genres = raw_movies[["movie_id"] + flag_columns].melt(
    id_vars="movie_id", var_name="genre_flag", value_name="present",
)
movie_genres = movie_genres.loc[movie_genres["present"].eq(1)].copy()
movie_genres["genre_id"] = movie_genres["genre_flag"].str.removeprefix("genre_").astype(int)
movie_genres = movie_genres[["movie_id", "genre_id"]].merge(
    genres, on="genre_id", how="left", validate="many_to_one",
)
assert not movie_genres.duplicated(["movie_id", "genre_id"]).any()
assert movie_genres["genre"].notna().all()
assert len(movie_genres) == 2893
movie_genres.head()
```

`melt()` 把“每种类型一列”改为“每个电影类型组合一行”。只保留值为 1 的真实标签，unknown 也保留；不人为指定唯一主类型。

### 4.5 检查评分与电影关联有没有丢行或倍增

```python
rating_movies = ratings.merge(movies, on="movie_id", how="left",
                               validate="many_to_one", indicator=True)
assert len(rating_movies) == len(ratings)
assert rating_movies["_merge"].eq("both").all()
print(rating_movies["_merge"].value_counts())
```

`how="left"` 保留全部评分，让找不到电影的记录显露出来。`validate="many_to_one"` 要求电影侧每个 ID 唯一；如果右侧重复，它会报错，避免悄悄放大评分数。

现在有三张清晰的表：`ratings` 一条评分一行；`movies` 一电影 ID 一行；`movie_genres` 一电影类型组合一行。后面分析直接使用这些 DataFrame。

## 五、先定义指标和分母

| 指标 | 计算方式 | 注意点 |
|---|---|---|
| 月评分数 | 该月评分行数 | 不等于播放量 |
| 月评分用户数 | 当月去重用户数 | 不等于平台月活 |
| 人均评分数 | 月评分数 / 月评分用户数 | 分母是参与评分的人 |
| 日均评分数 | 完整月评分数 / 日历天数 | 控制月份长短，不以有记录天数替代日历天数 |
| Top10% 份额 | 前 `ceil(目录影片数×10%)` 部评分最多影片的评分数 / 总评分数 | 以全部目录 ID 为范围，并列按 ID 升序 |
| 高分比例 | 4/5 星条数 / 该片全部评分数 | 是已记录评分中的比例 |
| 类型分摊份额 | 类型分摊权重 / 总评分数 | 每条评分按影片类型数分摊 `1/k` |
| 收缩均分 | `(n×原均分 + m×全局均分)/(n+m)` | 是平滑排序，不是质量真值或显著性检验 |

本例长尾定义为评分数 ≤20；口碑候选至少 30 条评分；主收缩强度 `m=50`。这是分析选择，不是行业标准，也不是统计保证。

## 六、月度参与：人数还是人均提交量在变

### 为什么这样分析

```text
月评分数 = 月评分用户数 × 人均评分数
```

总量变化可以来自人数、人均量或两者同时变化。再看日均量，才能减少 28/30/31 天的差异。这个分解描述组成，不证明原因。

### 用 groupby 得到一月一行

```python
monthly_source = ratings.assign(rating_day=ratings["rated_at_utc"].dt.strftime("%Y-%m-%d"))
monthly = monthly_source.groupby("rating_month", as_index=False).agg(
    rating_count=("rating", "size"), scoring_users=("user_id", "nunique"),
    rated_movies=("movie_id", "nunique"), rating_mean=("rating", "mean"),
    observed_day_count=("rating_day", "nunique"),
)
monthly["calendar_days"] = pd.to_datetime(monthly["rating_month"] + "-01").dt.days_in_month
boundary_months = [ratings["rating_month"].min(), ratings["rating_month"].max()]
monthly["is_partial_month"] = monthly["rating_month"].isin(boundary_months).astype(int)
monthly["ratings_per_scoring_user"] = monthly["rating_count"] / monthly["scoring_users"]
monthly["day_normalized_ratings"] = (monthly["rating_count"] / monthly["calendar_days"]).where(monthly["is_partial_month"].eq(0))
assert monthly["rating_count"].sum() == 100000
assert np.allclose(monthly["rating_count"], monthly["scoring_users"] * monthly["ratings_per_scoring_user"])
monthly
```

`size` 数记录，`nunique` 数不同用户或电影，`mean` 算评分均值。使用命名聚合，把每列含义直接写在结果列名里。

### 只对完整日历月画比较图

```python
complete_months = monthly.loc[monthly["is_partial_month"].eq(0)].copy()
assert complete_months["rating_month"].tolist() == ["1997-10", "1997-11", "1997-12", "1998-01", "1998-02", "1998-03"]
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

首尾两个月仅覆盖部分日期，单列而不与完整月直接解释增长。中间月份覆盖日历范围，也不意味着捕获了全平台行为。

实际观察：1997-10 到 1997-11，月评分数从 10,304 增至 23,980（+132.7%）；评分用户从 152 增至 288（+89.5%），人均量从 67.79 增至 83.26（+22.8%）。人数和人均提交量都参与了记录量的增长；这只是恒等分解，不证明某个原因造成了增长。随后月份也不呈持续单向上升。

另一个需要追问的质量细节：1997-12 有 31 个日历日，但只有 29 天出现评分记录。日历日均仍以 31 为分母；另外两天没有记录，不能证明它们没有用户行为，也可能与采样或记录机制有关。

**结论与建议：** 增长同时伴随参与人数和人均提交量增加；可能受样本组成或记录机制影响。实际业务应结合活动日历、曝光和播放记录核查，不能仅凭评分数据归因于内容质量，也不能把不再评分当作用户流失。

## 七、集中度：先变成一片一行，再计算累计占比

### 为什么要改变粒度

评分明细是一条评分一行，研究电影集中度必须先按电影聚合。目录范围包括全部电影 ID，即使未来数据里出现零评分电影，也应保留在目录分母中。

```python
movie_counts = ratings.groupby("movie_id", as_index=False).agg(rating_count=("rating", "size"))
movie_counts = movies[["movie_id"]].merge(movie_counts, on="movie_id", how="left", validate="one_to_one")
movie_counts["rating_count"] = movie_counts["rating_count"].fillna(0).astype(int)
movie_counts = movie_counts.sort_values(["rating_count", "movie_id"], ascending=[False, True]).reset_index(drop=True)
movie_counts["count_rank"] = np.arange(1, len(movie_counts) + 1)
movie_counts["cumulative_share"] = movie_counts["rating_count"].cumsum() / movie_counts["rating_count"].sum()
assert movie_counts["rating_count"].sum() == len(ratings)
movie_counts.head()
```

`merge` 保留目录范围；这里只把“目录里有但无评分”的计数填 0，不是把缺失评分填成 0 星。`sort_values` 固定并列顺序，`cumsum` 计算累计评分量。

```python
top10_n = int(np.ceil(len(movie_counts) * 0.10))
top20_n = int(np.ceil(len(movie_counts) * 0.20))
tail = movie_counts["rating_count"].le(20)
concentration = {
    "movie_count": int(len(movie_counts)), "rating_count": int(len(ratings)),
    "top10_movie_count": top10_n,
    "top10_rating_share": float(movie_counts.head(top10_n)["rating_count"].sum() / len(ratings)),
    "top20_movie_count": top20_n,
    "top20_rating_share": float(movie_counts.head(top20_n)["rating_count"].sum() / len(ratings)),
    "longtail_movie_count": int(tail.sum()),
    "longtail_movie_share": float(tail.mean()),
    "longtail_rating_share": float(movie_counts.loc[tail, "rating_count"].sum() / len(ratings)),
}
assert top10_n == 169 and top20_n == 337
print(json.dumps(concentration, ensure_ascii=False, indent=2))
```

### 看分布，而不只看一个百分比

```python
ordered = np.sort(movie_counts["rating_count"].to_numpy())
x = np.r_[0, np.arange(1, len(ordered) + 1) / len(ordered)]
y = np.r_[0, np.cumsum(ordered) / ordered.sum()]
fig, ax = plt.subplots(figsize=(6, 5))
ax.plot(x, y, label="Observed rating concentration")
ax.plot([0, 1], [0, 1], "--", color="gray", label="Equal counts reference")
ax.set(xlabel="Movie share (least rated first)", ylabel="Cumulative rating share")
ax.legend()
fig.tight_layout()
fig.savefig(OUTPUT / "concentration.svg", metadata={"Date": None})
plt.show()
```

累计头部表按评分数降序；这里的 Lorenz 图按升序，从少评分影片开始。别把两种排序方向混为一谈。

本次结果：前 10%（向上取整为 **169 部**）影片获得 **42,871 / 100,000 = 42.87%** 的评分；前 20%（337 部）占 **64.72%**。≤20 条评分的电影有 **755 部，占目录影片 44.89%**，但合计只占评分 **5.27%**。

这表示样本中的观测证据分布不均；不是对所有内容都拥有同等可靠的评分估计。

**结论与建议：** 评分证据分布不均，低样本片的均分容易波动。候选榜应同时展示量和分；要判断长尾片是否被低估，还需曝光、播放和评价提交率，评分份额不等于流量或市场份额。

## 八、类型分析：先看重复，再决定分摊口径

### 展开类型会发生什么

```python
genre_sizes = movie_genres.groupby("movie_id", as_index=False).size().rename(columns={"size": "n_genres"})
assert not movie_genres.duplicated(["movie_id", "genre_id"]).any()
tagged = ratings.merge(movie_genres, on="movie_id", how="left", validate="many_to_many")
tagged = tagged.merge(genre_sizes, on="movie_id", how="left", validate="many_to_one")
assert tagged["genre_id"].notna().all()
print("原评分：", len(ratings), "；类型展开后：", len(tagged))
tagged[["movie_id", "genre", "rating", "n_genres"]].head()
```

类型关联把 **100,000 条评分**展开成 **212,595 行**。例如一条属于三个标签的影片评分，会出现三次。

`many_to_many` 只是声明允许多对多，不会自动发现重复键，所以前面必须单独检查电影类型组合唯一性。展开出的多行也不是新的独立评分。

### 为什么分摊 1/k

- 全额计数让一条三类型电影评分分别进入三个类型，回答“带该标签的电影获得了多少评分”，但类型总量不可直接相加。
- 若要一份合计为 100% 的类型结构，则给每个标签 `1/类型数` 的权重。这是记账假设，不代表观众的注意力平均分给标签。

```python
tagged["weight"] = 1.0 / tagged["n_genres"]
tagged["weighted_rating"] = tagged["weight"] * tagged["rating"]
tagged["is_high"] = tagged["rating"].ge(4).astype(float)
assert np.isclose(tagged["weight"].sum(), len(ratings))

genre = tagged.groupby(["genre_id", "genre"], as_index=False).agg(
    movie_count=("movie_id", "nunique"), scoring_users=("user_id", "nunique"),
    rating_count=("rating", "size"), rating_mean=("rating", "mean"),
    high_rating_ratio=("is_high", "mean"), weighted_count=("weight", "sum"),
    weighted_rating_sum=("weighted_rating", "sum"),
)
genre["weighted_rating_mean"] = genre["weighted_rating_sum"] / genre["weighted_count"]
genre["weighted_share"] = genre["weighted_count"] / len(ratings)
per_movie = ratings.groupby("movie_id", as_index=False).agg(movie_mean=("rating", "mean"))
equal_movie = movie_genres.merge(per_movie, on="movie_id", validate="many_to_one").groupby(
    "genre_id", as_index=False).agg(equal_movie_weight_mean=("movie_mean", "mean"))
genre = genre.merge(equal_movie, on="genre_id", validate="one_to_one").drop(columns="weighted_rating_sum")
genre = genre.sort_values(["weighted_count", "genre_id"], ascending=[False, True]).reset_index(drop=True)
assert np.isclose(genre["weighted_share"].sum(), 1.0)
genre.head()
```

三种均值的含义必须分清：

分摊权重可能出现微小浮点误差，例如总和显示为 `99999.99999999999`，因此用 `np.isclose()` 核对是否足够接近十万，而不是要求浮点值逐位相等。

- `rating_mean`：标签内每条评分等权，评分多的影片贡献更多。
- `weighted_rating_mean`：每条评分按 `1/k` 计权，多类型片在每个标签中贡献更少。
- `equal_movie_weight_mean`：先算每片均分，再对类型内电影等权。

| 类型 | 带该标签的影片数 | 全额关联评分行 | 分摊评分份额 | 分摊加权均分 | 电影等权均分 |
|---|---|---|---|---|---|
| Drama | 725 | 39,895 | 24.61% | 3.683 | 3.187 |
| Comedy | 505 | 29,832 | 18.29% | 3.350 | 3.001 |
| Action | 251 | 25,589 | 9.59% | 3.423 | 2.966 |
| Thriller | 251 | 21,872 | 9.40% | 3.496 | 3.137 |
| Romance | 247 | 19,461 | 8.10% | 3.582 | 3.244 |

上表按分摊评分份额取前五类，不是按最高均分挑选。所有 19 个类型均包含在聚合结果中；unknown 未删除。

**结论与建议：** 这描述了样本的类型记录结构与评分反馈。标签重叠、目录构成、用户选择和是否评分都会影响差异；不能说某类型导致满意度更高，也不能用类型评分份额推断供需缺口。需要将它与目录、曝光、播放等相同口径数据对照。类型独立用户数也不能跨类型相加。

## 九、候选榜：为什么均分高不一定证据强

### 先按片聚合，再应用公开的分析规则

1 条 5 星评分和 200 条平均 4.3 星评分，证据量不同。我们固定候选至少 30 条评分，并同时展示均分、数量和高分比例。

```python
movie_stats = ratings.assign(is_high=ratings["rating"].ge(4).astype(float)).groupby(
    "movie_id", as_index=False).agg(rating_count=("rating", "size"),
                                    raw_mean=("rating", "mean"), high_rating_ratio=("is_high", "mean"))
candidates = movie_stats.loc[movie_stats["rating_count"].ge(30)].merge(
    movies[["movie_id", "title"]], on="movie_id", validate="one_to_one")
global_mean = float(ratings["rating"].mean())
prior_strength = 50
candidates["global_mean"] = global_mean
candidates["prior_strength"] = prior_strength
candidates["shrunk_mean"] = (
    candidates["rating_count"] * candidates["raw_mean"] + prior_strength * global_mean
) / (candidates["rating_count"] + prior_strength)
candidates = candidates.sort_values(["shrunk_mean", "rating_count", "movie_id"],
                                      ascending=[False, False, True]).reset_index(drop=True)
candidates["shrunk_rank"] = np.arange(1, len(candidates) + 1)
candidates[["title", "rating_count", "raw_mean", "high_rating_ratio", "shrunk_mean", "shrunk_rank"]].head(10)
```

全局均分从全部有效评分计算，不能改成候选均分或各电影均分的简单平均。

```text
收缩分 = (n × 该片原均分 + m × 全局均分) / (n + m)
```

当 n 小，结果更接近全局均分；n 大，更接近该片原均分。收缩是向全局均值靠拢，不是所有分数一律降低。它是稳定排序的方法，不是质量真值或显著性结论；30 条与 m=50 都是透明的演示选择。

| 收缩排名 | 影片 | 评分数 | 原均分 | 收缩分 | 4/5 星比例 |
|---|---|---|---|---|---|
| 1 | Schindler's List (1993) | 298 | 4.466 | 4.332 | 88.9% |
| 2 | Shawshank Redemption, The (1994) | 283 | 4.445 | 4.308 | 90.1% |
| 3 | Casablanca (1942) | 243 | 4.457 | 4.299 | 88.9% |
| 4 | Star Wars (1977) | 583 | 4.358 | 4.293 | 85.9% |
| 5 | Usual Suspects, The (1995) | 267 | 4.386 | 4.251 | 86.9% |

本次共有 806 部影片达到 30 条门槛，全局均分为 3.52986。例如 A Close Shave 的原均分约 4.491、112 条评分，m=50 后约 4.194；Schindler's List 的原均分约 4.466、298 条评分，收缩后约 4.332。排序改变反映样本量与规则的影响，不能由此断言哪部片客观更好。

### 改变参考强度，看名单是否依赖单一参数

```python
sensitivity_frames = []
for strength in [20, 50, 100]:
    scored = candidates.copy()
    scored["prior_strength"] = strength
    scored["shrunk_mean"] = (scored["rating_count"] * scored["raw_mean"] + strength * global_mean) / (scored["rating_count"] + strength)
    scored = scored.sort_values(["shrunk_mean", "rating_count", "movie_id"], ascending=[False, False, True]).head(20).copy()
    scored["shrunk_rank"] = np.arange(1, len(scored) + 1)
    sensitivity_frames.append(scored)
sensitivity = pd.concat(sensitivity_frames, ignore_index=True)
top_sets = {int(value): set(rows["movie_id"]) for value, rows in sensitivity.groupby("prior_strength")}
overlap_rows = []
for left, right in [(20, 50), (50, 100), (20, 100)]:
    overlap_rows.append({"left_m": left, "right_m": right,
                         "shared_movies": len(top_sets[left] & top_sets[right]),
                         "jaccard": len(top_sets[left] & top_sets[right]) / len(top_sets[left] | top_sets[right])})
pd.DataFrame(overlap_rows)
```

| 参考强度对比 | Top20 共同影片 | Jaccard（交集/并集） |
|---|---|---|
| 20 vs 50 | 19 / 20 | 90.48% |
| 20 vs 100 | 17 / 20 | 73.91% |
| 50 vs 100 | 18 / 20 | 81.82% |

这是名单集合的交集，不说明共同影片排名顺序相同。m=20 与 m=100 有 17 部共同影片，也意味着有边缘候选会随收缩强度变化。

这检查分析选择的敏感性，不是独立样本验证；共同影片不代表排名顺序相同。稳定名单可供编辑复核，不能直接承诺上线效果。

**亲手练习：** 把最少评分数 30 分别改成 20、50，记录被排除多少电影、Top20 名单如何变化，以及结论是否改变。不要在看到喜欢的电影上榜后才决定阈值。

## 十、从数字写到结论，再写建议

每条结论沿这条线展开：

```text
现象（数字、范围和分母）
→ 有限解释（支持什么）
→ 替代解释（还可能受什么影响）
→ 行动候选（准备尝试什么）
→ 验证计划（补什么数据、怎样判断）
```

| 实证观察 | 有限解释与替代解释 | 行动候选 | 还需什么验证 |
|---|---|---|---|
| 10→11 月评分用户 152→288，人均 67.79→83.26 | 记录量增长同时伴随人数与人均提交量增加；可能受样本组成和记录方式影响 | 先核查记录范围与参与机制，不直接归因于内容改善 | 活动日历、数据采集变更与曝光/播放日志 |
| 前169部占评分42.87%；755部长尾只占5.27% | 评分证据集中；小样本片的均分更容易波动 | 榜单同时展示量与分，不只按均分决策 | 曝光、观看及评价提交率，区分未被看见与反馈较低 |
| Drama/Comedy 分摊评分份额约24.61%/18.29% | 描述本样本的类型记录结构，不是市场需求；标签和目录构成也会影响份额 | 将评分结构与内容供给、曝光结构一起检查 | 同口径的目录、曝光和播放分母 |
| m20与m100的Top20共同17部 | 部分边缘候选依赖分析规则；名单稳定也不等于上线有效 | 将稳定且量足的对象列为编辑复核候选，记录边缘项 | 内容可用性、业务目标和预设的线上对照实验 |

这是一份公开历史数据的模拟分析。是否增加曝光、调整目录或选择内容，仍需业务背景、内容可用性与后续验证。没有实验数据时，不预写留存、播放或收入提升幅度。

## 十一、保存证据并写自己的报告

保存聚合结果，不保存逐用户或逐条评分明细：

```python
evidence = {name: json.loads(frame.to_json(orient="records")) for name, frame in {
    "monthly": monthly,
    "genre": genre,
    "top30_candidates": candidates.head(30),
    "sensitivity": sensitivity[["prior_strength", "movie_id", "title", "rating_count", "raw_mean", "shrunk_mean", "shrunk_rank"]],
    "top20_overlap": pd.DataFrame(overlap_rows),
}.items()}
evidence["concentration"] = concentration
evidence["quality"] = quality
evidence["source_sha256"] = SOURCE_SHA256
(OUTPUT / "evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("聚合证据保存到：", OUTPUT / "evidence.json")
```

建立 `docs/MY_ANALYSIS.md`，写出自己的理解：

```markdown
# 我的 MovieLens 数据分析

## 分析任务
模拟谁的需求，四个具体问题是什么？

## 来源和范围
版本、粒度、UTC时间、筛选条件、缺失哪些业务数据？

## 数据质量和处理
检查、实际发现、保留/转换/待核查的决定及理由，前后数量。

## 指标和方法
groupby、merge、累计占比、1/k分摊、收缩排序为什么适合这些问题？

## 结果和解释
每个问题一张表或图，一条带数字的观察，一条替代解释。

## 建议和验证
哪些仅是候选方案，还需要哪些数据？

## 限制和复现
样本、年代、选择性评分、参数敏感性；代码版本和输出位置。
```

完整参考：[分析报告](../reports/analyst/ANALYSIS_REPORT.md)、[聚合指标](../reports/analyst/metrics.json)、[质量审计](../reports/analyst/audit.json)。面试时如实描述为个人公开数据案例，不能包装成企业真实增长项目。

## 十二、最后再看封装好的自动流程

你已经逐步看到了 DataFrame 如何变成分析结果。现在可以运行项目的自动实现，核对结果并理解函数封装：

```python
from rating_lab.analyst import run_analysis

reference_result = run_analysis(DATA, PROJECT / "reports/analyst")
for name, manual, key, columns in [
    ("monthly", monthly, "rating_month", ["rating_month", "rating_count", "scoring_users", "day_normalized_ratings"]),
    ("genre", genre, "genre_id", ["genre_id", "weighted_count", "weighted_rating_mean", "weighted_share"]),
    ("movie_candidates", candidates.head(30), "shrunk_rank", ["shrunk_rank", "movie_id", "rating_count", "raw_mean", "shrunk_mean"]),
]:
    expected = pd.DataFrame(reference_result[name])
    pd.testing.assert_frame_equal(
        manual[columns].sort_values(key).reset_index(drop=True),
        expected[columns].sort_values(key).reset_index(drop=True),
        check_dtype=False, check_exact=False, rtol=1e-9, atol=1e-8,
    )
for name, value in concentration.items():
    assert np.isclose(value, reference_result["concentration"][name])
print("手工过程与自动流程的关键结果一致")
```

上面的核对先按月份或类型 ID 等键对齐，再逐列比较数值；只看总和相同并不能证明各类型都分对了。JSON 会有数值精度差异，因此使用小容差，且保留完整的键和排序核对。

主实现是 [analyst.py](../src/rating_lab/analyst.py)：`prepare_data()` 返回处理后的 DataFrame 与审计字典，五个 `analyze_*()` 函数分别计算月度、集中度、候选、类型和敏感性。`run_analysis()` 将它们组织起来并写报告；这些函数封装的是你前面已经看懂的操作。

### 完成标准

- [ ] 能解释原表粒度、来源和样本范围。
- [ ] 每个质量处理决定都有理由与数量，1/5 星和同名条目没有被盲删。
- [ ] 能用 `melt` 拆标签，用 `merge(validate=...)` 核对关联关系。
- [ ] 清楚 `size`、`nunique`、`mean` 分别算什么。
- [ ] 月度总量、人均量和日均量口径明确，部分月份单列。
- [ ] 集中度先聚合电影，再排序、累计，目录分母没有丢失。
- [ ] 能解释 212,595 行展开与 100,000 权重守恒。
- [ ] 三种类型均值含义清楚，收缩分不是显著性证据。
- [ ] 改过至少一个样本门槛，保留敏感性结果。
- [ ] 建议有数字、替代解释、限制和验证计划。
- [ ] Notebook 重启后能从头运行；发布前清空输出。

### 运行与文件

直接打开配套 Notebook 逐格运行，或在项目目录使用 `python -m rating_lab.analyst` 复现完整参考结果。依赖为 numpy、pandas、matplotlib；缺少时在当前环境使用 `python -m pip install -e .`。自有分析输出位于 `reports/analyst_learning/`，自动参考位于 `reports/analyst/`。

原包只留在本地 `data/`。原有评分预测代码是可选的 Python 技术扩展，不属于当前岗位分析主线。

数据适用 GroupLens 单独许可，代码许可不覆盖源数据。不要提交原包、逐条评分、逐用户输出或训练参数。引用：Harper & Konstan (2015), *The MovieLens Datasets: History and Context*. [DOI: 10.1145/2827872](https://doi.org/10.1145/2827872).
