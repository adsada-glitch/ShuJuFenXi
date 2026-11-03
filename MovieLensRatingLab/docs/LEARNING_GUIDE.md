# 从已下载数据开始：先建立 rating_lab，再逐步分析

本教程的顺序是：**先建立自己的包 → 写完整的读取函数并保存 → 导入读取 → 写完整的清洗函数并保存 → 导入处理 → 逐个编写分析模块并调用 → 总结。**

你已经有本地 `ml-100k.zip`。我们不下载数据、不调用仓库预先写好的分析函数；每一个自己定义的函数，都会在第一次使用之前给出所在 `.py` 文件的全部内容。

打开 [配套 Notebook](../notebooks/01_explore.ipynb)。第一次学习时，每遇到“保存为某文件”的内容，先按说明创建文件并保存，再运行下一格。**不能跳过保存文件，直接把所有单元格运行到底。** 所有模块建立后，才可以重启内核、从头完整运行。

## 第 1 步：现在就建立自己的 rating_lab

### 1.1 建立学习目录

可以用一个新文件夹；使用本仓库时，可以在 `notebooks` 目录练习。把 Notebook 和已下载的 ZIP 放在同一级：

```text
你的学习文件夹/
  01_explore.ipynb
  ml-100k.zip
  rating_lab/             ← 第一步就创建这个文件夹
    __init__.py           ← 第一步就创建这个文件
  outputs/                ← 稍后保存聚合证据
```

后面会逐个添加 `data_io.py`、`cleaning.py`、`monthly.py`、`concentration.py`、`genres.py`、`candidates.py`。这些文件在对应步骤写好后才导入，不需要提前猜内容。

### 1.2 保存 __init__.py 的完整内容

用编辑器在学习文件夹中新建 `rating_lab` 文件夹，再新建 `__init__.py`。下面是文件的全部内容，请保存到磁盘；不是只在 Notebook 中执行。

```python
# file: rating_lab/__init__.py
"""我自己编写的 MovieLens 数据分析工具。"""
```

`__init__.py` 说明这是一个普通 Python 包。这里先不导入尚未建立的其他模块。

### 1.3 确认能导入自己建立的包

保存文件后，运行下面的第一格。`WORK` 是当前学习目录；先检查打印位置是否就是 Notebook 与 `rating_lab` 所在的文件夹。

```python
from pathlib import Path
import hashlib
import json

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

WORK = Path.cwd()
ZIP_PATH = WORK / "ml-100k.zip"
OUTPUT = WORK / "outputs"
OUTPUT.mkdir(parents=True, exist_ok=True)
print("当前学习目录：", WORK)
assert (WORK / "rating_lab/__init__.py").is_file(), "请先创建并保存 rating_lab/__init__.py"

import rating_lab
print("实际导入的包：", rating_lab.__file__)
assert Path(rating_lab.__file__).resolve() == (WORK / "rating_lab/__init__.py").resolve(), "导入了其他同名包，请重启内核并确认学习目录"
assert ZIP_PATH.is_file(), "请把已下载的 ml-100k.zip 放到当前学习目录，或修改 ZIP_PATH"
```

如果 ZIP 在下载目录，可以只修改 `ZIP_PATH`，填入文件的真实绝对路径。这里不查找项目源码，不修改 `sys.path`，也不要求安装这个仓库。

如果曾在同一内核导入过旧的 `rating_lab`，先重启内核，确认当前学习目录后再开始。不要通过跳过路径检查来掩盖导入了其他包的问题。

**本步完成条件：** 你已经自己创建包，`rating_lab.__file__` 指向自己的学习目录。此时还没有开始读取或分析数据。

## 第 2 步：明确数据来源和分析问题

本例模拟内容编辑任务，回答四个问题：月度评分参与怎样变化？评分是否集中在少数影片？多类型电影怎样比较？哪些影片值得进入兼顾评分量与口碑的候选名单？

使用固定的 MovieLens 100K：[官方介绍](https://grouplens.org/datasets/movielens/100k/)、[原包](https://files.grouplens.org/datasets/movielens/ml-100k.zip)、[字段说明和许可](https://files.grouplens.org/datasets/movielens/ml-100k-README.txt)。

数据有 100,000 条评分、943 位用户、1,682 个电影目录 ID。UTC 评分时间覆盖 1997-09-20 至 1998-04-22；用户经过至少 20 条评分等筛选。历史年代、样本选择和主动评分机制限制了结论外推。

| 文件 | 一行代表什么 | 本次使用 |
|---|---|---|
| `u.data` | 用户提交的一条电影评分 | 用户ID、电影ID、1–5星、提交时间 |
| `u.item` | 一个电影目录ID | 标题、发行日期、19个类型标记 |
| `u.genre` | 一种类型 | 编码与名称 |
| `u.user` | 一位入选用户 | 只取ID检查关联 |

评分不是播放记录；评分用户数不是平台月活。没有曝光、观看、注册或收入数据，不能直接计算真实留存、转化和收入贡献。这个案例是公开数据模拟分析，不声称带来真实业务增长。

先确认自己下载的是同一版本：

```python
SOURCE_SHA256 = "50d2a982c66986937beb9ffb3aa76efe955bf3d5c6b761f4e3a7cd717c6a3229"
assert hashlib.sha256(ZIP_PATH.read_bytes()).hexdigest() == SOURCE_SHA256, "请核对是否为官方 MovieLens 100K 原包"
```

## 第 3 步：先写 data_io.py，再导入读取

### 3.1 为什么建立这个模块

它只负责从已经存在的 ZIP 读取原始表，不负责清洗或分析。

- 输入：ZIP 文件路径。
- 输出：评分原表、电影原表、类型表、用户 ID 表、类型标记列名。
- 读取方式：`u.data` 按制表符分隔；`u.item` 和类型表按 `|` 分隔，明确 Latin-1 编码。

在 `rating_lab` 下新建 `data_io.py`，保存以下全部内容：

```python
# file: rating_lab/data_io.py
"""从本地固定原包读取四张原始表，不下载或修改源数据。"""

import hashlib
import io
from pathlib import Path
import zipfile

import pandas as pd


def read_source_tables(zip_path):
    """返回评分、电影、类型、用户ID原表，以及类型标记列名。"""
    zip_path = Path(zip_path)
    expected_hash = "50d2a982c66986937beb9ffb3aa76efe955bf3d5c6b761f4e3a7cd717c6a3229"
    if hashlib.sha256(zip_path.read_bytes()).hexdigest() != expected_hash:
        raise ValueError("原包校验和不符，请核对来源和版本")
    with zipfile.ZipFile(zip_path) as source:
        ratings_raw = pd.read_csv(
            io.BytesIO(source.read("ml-100k/u.data")), sep="\t",
            names=["user_id", "movie_id", "rating", "timestamp"],
        )
        genres = pd.read_csv(
            io.BytesIO(source.read("ml-100k/u.genre")), sep="|",
            names=["genre", "genre_id"], encoding="latin-1",
        )
        flag_columns = [f"genre_{value}" for value in genres.sort_values("genre_id")["genre_id"]]
        raw_movies = pd.read_csv(
            io.BytesIO(source.read("ml-100k/u.item")), sep="|", encoding="latin-1",
            names=["movie_id", "title", "release_date_raw", "video_release_date_raw", "imdb_url"] + flag_columns,
            keep_default_na=False,
        )
        users = pd.read_csv(
            io.BytesIO(source.read("ml-100k/u.user")), sep="|", header=None,
            usecols=[0], encoding="latin-1",
        ).rename(columns={0: "user_id"})
    return ratings_raw, raw_movies, genres, users, flag_columns
```

### 3.2 保存后才导入调用

```python
import rating_lab.data_io as data_module

ratings_raw, raw_movies, genres, users, flag_columns = data_module.read_source_tables(ZIP_PATH)
print("评分原表：", ratings_raw.shape)
print("电影原表：", raw_movies.shape)
print("类型表：", genres.shape)
print(ratings_raw.dtypes)
ratings_raw.head()
```

预期评分形状 `(100000, 4)`，电影 `(1682, 24)`，类型 19 行。`data_module` 是你刚保存的模块，`ratings_raw` 才是结果表；名字区分开，避免把模块覆盖成 DataFrame。

源码中的 `ZipFile.read()` 取出成员字节，`BytesIO()` 把它变成可读文件对象，`pd.read_csv()` 解析表格。`names` 给没有标题行的源文件列名；`keep_default_na=False` 先保留原始空字符串。

一行是一条评分，不是一位用户。ID 是标识符，不能按数值大小解释质量或活跃度。

## 第 4 步：先写 cleaning.py，再导入处理

### 4.1 处理前先决定规则

| 检查 | 风险 | 决策 |
|---|---|---|
| 评分关键字段缺失、重复组合、越界 | 无法确认含义或重复计权 | 显式检查，关键错误停止，不默默填0 |
| 电影ID重复或关联不到 | 关联倍增、遗漏 | 检查键关系，不用内连接隐藏问题 |
| 同名不同ID | 误合并或误删 | 保留源ID，记录待核查项 |
| 发行日期缺失 | 日期分析有空值 | 保留NaT，不删除其他有效数据 |
| 视频日期、URL缺失 | 对无关字段过度清洗 | 不对全表一律dropna |
| 1星、5星 | 误删合法极端评分 | 都是有效评分，保留 |
| 一片多标签 | 重复计算 | 用melt建类型关联表，再在分析时明确分摊 |

### 4.2 保存完整清洗函数

输入是上一步的原始表，输出是处理后的三张表与质量记录。函数中的顺序是：检查 → 转时间和日期 → 拆类型 → 核对关联与数量。

在 `rating_lab/cleaning.py` 保存以下全部内容：

```python
# file: rating_lab/cleaning.py
"""检查质量、统一日期并建立类型桥表；不按标题或评分高低删行。"""

import numpy as np
import pandas as pd


def clean_tables(ratings_raw, raw_movies, genres, users, flag_columns):
    """显式接收原表，返回三张处理后表和质量记录，不修改输入。"""
    if ratings_raw.empty or raw_movies.empty:
        raise ValueError("评分与电影原表不能为空")
    rating_time = pd.to_datetime(ratings_raw["timestamp"], unit="s", utc=True, errors="coerce")
    release_dates = pd.to_datetime(raw_movies["release_date_raw"], format="%d-%b-%Y", errors="coerce")
    release_present = raw_movies["release_date_raw"].ne("")
    quality = {
        "rating_rows": len(ratings_raw),
        "missing_rating_cells": int(ratings_raw.isna().sum().sum()),
        "duplicate_user_movie_pairs": int(ratings_raw.duplicated(["user_id", "movie_id"]).sum()),
        "out_of_range_ratings": int((~ratings_raw["rating"].between(1, 5)).sum()),
        "duplicate_movie_ids": int(raw_movies["movie_id"].duplicated().sum()),
        "duplicate_title_groups": int((raw_movies["title"].value_counts() > 1).sum()),
        "missing_release_dates": int((~release_present).sum()),
        "missing_video_dates": int(raw_movies["video_release_date_raw"].eq("").sum()),
        "missing_urls": int(raw_movies["imdb_url"].eq("").sum()),
        "invalid_dates": int((release_present & release_dates.isna()).sum()),
        "invalid_timestamps": int(rating_time.isna().sum()),
        "duplicate_user_ids": int(users["user_id"].duplicated().sum()),
        "duplicate_genre_ids": int(genres["genre_id"].duplicated().sum()),
        "missing_dimension_key_cells": int(raw_movies["movie_id"].isna().sum()
                                           + users["user_id"].isna().sum()
                                           + genres["genre_id"].isna().sum()),
        "orphan_rating_user_rows": int((~ratings_raw["user_id"].isin(users["user_id"])).sum()),
        "orphan_rating_movie_rows": int((~ratings_raw["movie_id"].isin(raw_movies["movie_id"])).sum()),
        "invalid_genre_flag_cells": int((~raw_movies[flag_columns].isin([0, 1])).sum().sum()),
    }
    critical = ["missing_rating_cells", "duplicate_user_movie_pairs", "out_of_range_ratings",
                "duplicate_movie_ids", "invalid_timestamps", "duplicate_user_ids", "duplicate_genre_ids",
                "missing_dimension_key_cells", "orphan_rating_user_rows", "orphan_rating_movie_rows",
                "invalid_genre_flag_cells"]
    errors = {name: quality[name] for name in critical if quality[name]}
    if errors:
        raise ValueError(f"关键数据检查失败：{errors}")

    ratings = ratings_raw.copy()
    ratings["rated_at_utc"] = rating_time
    ratings["rating_month"] = rating_time.dt.strftime("%Y-%m")
    movies = raw_movies[["movie_id", "title"]].copy()
    movies["release_date"] = release_dates
    movies["release_year"] = release_dates.dt.year.astype("Int64")
    movie_genres = raw_movies[["movie_id"] + flag_columns].melt(
        id_vars="movie_id", var_name="genre_flag", value_name="present",
    )
    movie_genres = movie_genres.loc[movie_genres["present"].eq(1)].copy()
    movie_genres["genre_id"] = movie_genres["genre_flag"].str.removeprefix("genre_").astype(int)
    movie_genres = movie_genres[["movie_id", "genre_id"]].merge(
        genres, on="genre_id", how="left", validate="many_to_one",
    )
    quality["duplicate_movie_genre_pairs"] = int(movie_genres.duplicated(["movie_id", "genre_id"]).sum())
    quality["movies_without_genre"] = int((~movies["movie_id"].isin(movie_genres["movie_id"])).sum())
    if quality["duplicate_movie_genre_pairs"] or quality["movies_without_genre"] or movie_genres["genre"].isna().any():
        raise ValueError("电影类型组合必须唯一，每部电影须有可识别的真实类型标记")
    genre_sizes = movie_genres.groupby("movie_id").size()
    quality["multi_genre_movies"] = int(genre_sizes.gt(1).sum())
    quality["unknown_genre_movies"] = int(movie_genres.loc[movie_genres["genre"].eq("unknown"), "movie_id"].nunique())
    quality["movie_genre_rows"] = len(movie_genres)

    joined = ratings.merge(movies, on="movie_id", how="left", validate="many_to_one", indicator=True)
    quality["rating_movie_join_rows"] = len(joined)
    quality["unmatched_rating_movie_rows"] = int(joined["_merge"].ne("both").sum())
    tagged = ratings.merge(movie_genres, on="movie_id", how="left", validate="many_to_many")
    quality["rating_genre_join_rows"] = len(tagged)
    quality["genre_weighted_rating_total"] = float((1.0 / tagged["movie_id"].map(genre_sizes)).sum())
    if len(joined) != len(ratings) or quality["unmatched_rating_movie_rows"]:
        raise ValueError("评分与电影的多对一关联没有保留原始评分粒度")
    if not np.isclose(quality["genre_weighted_rating_total"], len(ratings), rtol=1e-12, atol=1e-9):
        raise ValueError("类型展开后的1/k分摊未保留总评分权重")
    quality["clean_rating_rows"] = len(ratings)
    quality["clean_movie_rows"] = len(movies)
    return ratings, movies, movie_genres, quality
```

### 4.3 导入、调用、检查中间结果

```python
import rating_lab.cleaning as cleaning_module

ratings, movies, movie_genres, quality = cleaning_module.clean_tables(
    ratings_raw, raw_movies, genres, users, flag_columns,
)
print(pd.Series(quality).to_string())
print(ratings.dtypes)
print("处理后：", ratings.shape, movies.shape, movie_genres.shape)
ratings.head()
```

| 检查 | 实际结果 | 处理与理由 |
|---|---|---|
| 评分缺失 / 重复组合 / 越界 | 0 / 0 / 0 | 全部有效，保留 100,000 条 |
| 评分找不到电影 / 找不到用户 | 0 / 0 | ID关联完整，不通过关联删记录 |
| 电影 ID 重复 | 0 | 以 ID 为主键保留 1,682 条目录记录 |
| 同名不同 ID | 18 组，涉及 36 行 | 保留并标注；不能无依据按标题合并 |
| 发行日期缺失 / 非空日期解析失败 | 1 / 0 | 缺失保留 NaT，不删电影或关联评分 |
| 视频发行日期缺失 | 1682 | 本次不使用此字段，不造日期 |
| URL 缺失 | 3 | 不影响本次聚合，不据此删行 |
| 多类型 / unknown 类型电影 | 849 / 2 | 按真实标签拆桥表，unknown 保留 |
| 电影类型桥表行数 | 2893 | 与影片数不同，因为一片多标签 |

评分全部保留。18个同名组仍需核查，本次按源ID统计，不代表已经确认唯一作品；实际使用前应结合外部标识判断是否合并。

读源码时重点跟这四处：

1. `pd.to_datetime(..., utc=True)` 把提交时间统一为 UTC；时间戳不是观影时间。
2. 发行日期 `errors="coerce"` 转为 NaT；分别记录原本缺失和非空解析失败。
3. `melt()` 将类型标记列转成电影类型组合行，只保留真实值为1的标签。
4. `merge(validate=...)` 及关联检查防止意外倍增或漏行；多类型展开的增加是另一个明确的粒度。

现在 `ratings` 一条评分一行；`movies` 一个电影ID一行；`movie_genres` 一个电影类型组合一行。

## 第 5 步：把指标口径写清楚

| 指标 | 计算 | 含义与边界 |
|---|---|---|
| 月评分数 | 该月评分行数 | 不是播放量 |
| 月评分用户数 | 当月去重用户数 | 不是平台月活 |
| 人均评分数 | 月评分数/月评分用户数 | 分母是参与评分的人 |
| 日均评分数 | 完整月评分数/日历天数 | 控制月份长短，不用有记录天数代替日历天数 |
| Top10%份额 | 前ceil(目录数×10%)部电影评分量/全部评分量 | 目录ID为分母范围，并列按ID升序 |
| 类型分摊份额 | sum(1/该片类型数)/全部评分数 | 可加总为100%的记账口径 |
| 高分比例 | 该片4/5星评分数/该片全部评分数 | 不是所有观众满意度 |
| 收缩分 | (n×原均分+m×全局均分)/(n+m) | 稳定排序方法，不是质量真值或显著性检验 |

本例长尾定义为≤20条评分，候选至少30条，收缩强度m=50。这些是公开的分析选择，不是行业标准或统计保证。

## 第 6 步：先写 monthly.py，再做月度分析

### 6.1 为什么这样分析

`月评分数 = 月评分用户数 × 人均评分数`。先分解人数与人均量，再用日均量控制月份天数差异；这能描述变化组成，但不能证明变化原因。

输入处理后的评分表，输出一月一行的指标表。将以下完整内容保存到 `rating_lab/monthly.py`：

```python
# file: rating_lab/monthly.py
"""按UTC评分月统计记录量、评分人数、人均量与日均量。"""

import pandas as pd


def make_monthly_table(ratings):
    if ratings.empty or not pd.api.types.is_datetime64_any_dtype(ratings["rated_at_utc"]):
        raise ValueError("请传入已转换rated_at_utc日期列的非空评分表")
    source = ratings.assign(
        rating_month=ratings["rated_at_utc"].dt.strftime("%Y-%m"),
        rating_day=ratings["rated_at_utc"].dt.normalize(),
    )
    result = source.groupby("rating_month", as_index=False).agg(
        rating_count=("rating", "size"), scoring_users=("user_id", "nunique"),
        rated_movies=("movie_id", "nunique"), rating_mean=("rating", "mean"),
        observed_day_count=("rating_day", "nunique"),
    )
    result["calendar_days"] = pd.to_datetime(result["rating_month"] + "-01").dt.days_in_month
    boundary_months = [source["rating_month"].min(), source["rating_month"].max()]
    result["is_partial_month"] = result["rating_month"].isin(boundary_months).astype(int)
    result["ratings_per_scoring_user"] = result["rating_count"] / result["scoring_users"]
    result["day_normalized_ratings"] = (result["rating_count"] / result["calendar_days"]).where(result["is_partial_month"].eq(0))
    return result[["rating_month", "rating_count", "scoring_users", "rated_movies", "rating_mean",
                   "calendar_days", "observed_day_count", "is_partial_month", "day_normalized_ratings",
                   "ratings_per_scoring_user"]].sort_values("rating_month").reset_index(drop=True)
```

### 6.2 导入、计算，再画图

```python
import rating_lab.monthly as monthly_module

monthly_table = monthly_module.make_monthly_table(ratings)
assert monthly_table["rating_count"].sum() == len(ratings)
assert np.allclose(monthly_table["rating_count"], monthly_table["scoring_users"] * monthly_table["ratings_per_scoring_user"])
monthly_table
```

`groupby` 改成月度粒度；`size` 数记录，`nunique` 数独立用户，`mean` 算评分均值。首尾月份保守标成部分月份，日均比较只用中间完整日历月。

```python
complete_months = monthly_table.loc[monthly_table["is_partial_month"].eq(0)]
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

实际观察：1997-10 到 1997-11，月评分数从 10,304 增至 23,980（+132.7%）；评分用户从 152 增至 288（+89.5%），人均量从 67.79 增至 83.26（+22.8%）。人数和人均提交量都参与了记录量的增长；这只是恒等分解，不证明某个原因造成了增长。随后月份也不呈持续单向上升。

另一个需要追问的质量细节：1997-12 有 31 个日历日，但只有 29 天出现评分记录。日历日均仍以 31 为分母；另外两天没有记录，不能证明它们没有用户行为，也可能与采样或记录机制有关。

**建议：** 实际业务还要核查记录机制、样本组成、活动日历、曝光和播放，不能把评分增长归因于内容质量，也不能把没再评分当作用户流失。

## 第 7 步：先写 concentration.py，再分析集中度

### 7.1 为什么先一片一行

评分明细不能直接当电影排名。先按电影聚合，再关联完整目录、对无评分计数补0，最后稳定排序和累计。这个计数0不是给缺失评分补0星。

下面文件包含两个完整函数：第一个生成电影计数表，第二个从计数表汇总集中度。保存为 `rating_lab/concentration.py`：

```python
# file: rating_lab/concentration.py
"""先按目录电影计数，再按稳定顺序汇总头部与长尾评分份额。"""

import numpy as np
import pandas as pd


def make_movie_counts(ratings, movies):
    if ratings.empty or movies.empty or movies["movie_id"].duplicated().any():
        raise ValueError("评分与目录不能为空，且目录电影ID须唯一")
    if not ratings["movie_id"].isin(movies["movie_id"]).all():
        raise ValueError("有评分找不到对应的目录电影")
    counts = ratings.groupby("movie_id", as_index=False).agg(rating_count=("rating", "size"))
    result = movies[["movie_id"]].merge(counts, on="movie_id", how="left", validate="one_to_one")
    result["rating_count"] = result["rating_count"].fillna(0).astype(int)
    result = result.sort_values(["rating_count", "movie_id"], ascending=[False, True]).reset_index(drop=True)
    result["count_rank"] = np.arange(1, len(result) + 1)
    result["cumulative_share"] = result["rating_count"].cumsum() / result["rating_count"].sum()
    return result


def summarize_concentration(movie_counts):
    if movie_counts.empty or movie_counts["rating_count"].sum() <= 0:
        raise ValueError("电影计数表不能为空，且总评分量须大于0")
    counts = movie_counts.sort_values(["rating_count", "movie_id"], ascending=[False, True])
    movie_count, rating_count = len(counts), int(counts["rating_count"].sum())
    top10_n, top20_n = int(np.ceil(movie_count * .10)), int(np.ceil(movie_count * .20))
    top10_ratings = int(counts.head(top10_n)["rating_count"].sum())
    top20_ratings = int(counts.head(top20_n)["rating_count"].sum())
    tail = counts.loc[counts["rating_count"].le(20)]
    tail_ratings = int(tail["rating_count"].sum())
    return {
        "movie_count": movie_count, "rating_count": rating_count,
        "top10_movie_count": top10_n, "top10_rating_count": top10_ratings,
        "top10_rating_share": top10_ratings / rating_count,
        "top20_movie_count": top20_n, "top20_rating_count": top20_ratings,
        "top20_rating_share": top20_ratings / rating_count,
        "longtail_movie_count": len(tail), "longtail_movie_share": len(tail) / movie_count,
        "longtail_rating_count": tail_ratings, "longtail_rating_share": tail_ratings / rating_count,
    }
```

### 7.2 保存后导入并调用两个函数

```python
import rating_lab.concentration as concentration_module

movie_counts = concentration_module.make_movie_counts(ratings, movies)
concentration = concentration_module.summarize_concentration(movie_counts)
assert movie_counts["rating_count"].sum() == len(ratings)
print(json.dumps(concentration, ensure_ascii=False, indent=2))
movie_counts.head()
```

`sort_values` 固定评分数降序、电影ID升序，`cumsum` 算累计份额，Top比例部数向上取整。

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

累计头部表降序，Lorenz图从少评分影片开始按升序，两个方向不要混淆。

本次结果：前 10%（向上取整为 **169 部**）影片获得 **42,871 / 100,000 = 42.87%** 的评分；前 20%（337 部）占 **64.72%**。≤20 条评分的电影有 **755 部，占目录影片 44.89%**，但合计只占评分 **5.27%**。

这表示样本中的观测证据分布不均；不是对所有内容都拥有同等可靠的评分估计。

**建议：** 同时展示评分量和分数，对证据稀薄的长尾慎下结论。要识别是否被低估，还需曝光和播放分母，不能把评分份额当市场份额。

## 第 8 步：先写 genres.py，再处理多标签分析

### 8.1 为什么不能直接相加

一部三类型电影的每条评分展开后出现三次。全额计数适合描述“带该标签的影片获得多少评分”，但类型总量不可直接相加。若要合计为100%的类型结构，明确按每片类型数分摊 `1/k`。

这是记账假设，不代表真实注意力平均分配。下面函数完整展示展开、检查、权重和三种均值；保存为 `rating_lab/genres.py`：

```python
# file: rating_lab/genres.py
"""保留真实多标签，并对照全额计数、1/k分摊和电影等权均分。"""

import numpy as np
import pandas as pd


def make_genre_table(ratings, movie_genres):
    if ratings.empty or movie_genres.duplicated(["movie_id", "genre_id"]).any():
        raise ValueError("评分不能为空，电影类型组合须唯一")
    sizes = movie_genres.groupby("movie_id", as_index=False).size().rename(columns={"size": "n_genres"})
    tagged = ratings.merge(movie_genres, on="movie_id", how="left", validate="many_to_many")
    tagged = tagged.merge(sizes, on="movie_id", how="left", validate="many_to_one")
    if tagged["genre_id"].isna().any() or tagged["genre"].isna().any():
        raise ValueError("有评分找不到真实类型标记")
    tagged["weight"] = 1.0 / tagged["n_genres"]
    tagged["weighted_rating"] = tagged["weight"] * tagged["rating"]
    tagged["is_high"] = tagged["rating"].ge(4).astype(float)
    if not np.isclose(tagged["weight"].sum(), len(ratings), rtol=1e-12, atol=1e-9):
        raise ValueError("1/k分摊未保留总评分权重")
    result = tagged.groupby(["genre_id", "genre"], as_index=False).agg(
        movie_count=("movie_id", "nunique"), scoring_users=("user_id", "nunique"),
        rating_count=("rating", "size"), rating_mean=("rating", "mean"),
        high_rating_ratio=("is_high", "mean"), weighted_count=("weight", "sum"),
        weighted_rating_sum=("weighted_rating", "sum"),
    )
    result["weighted_rating_mean"] = result["weighted_rating_sum"] / result["weighted_count"]
    result["weighted_share"] = result["weighted_count"] / len(ratings)
    per_movie = ratings.groupby("movie_id", as_index=False).agg(movie_mean=("rating", "mean"))
    equal_movie = movie_genres.merge(per_movie, on="movie_id", validate="many_to_one").groupby(
        "genre_id", as_index=False).agg(equal_movie_weight_mean=("movie_mean", "mean"))
    result = result.merge(equal_movie, on="genre_id", validate="one_to_one").drop(columns="weighted_rating_sum")
    result = result.sort_values(["weighted_count", "genre_id"], ascending=[False, True]).reset_index(drop=True)
    return result, tagged
```

### 8.2 导入后同时查看结果表和展开明细

```python
import rating_lab.genres as genres_module

genre_table, tagged_ratings = genres_module.make_genre_table(ratings, movie_genres)
print("原评分行数：", len(ratings), "；类型展开行数：", len(tagged_ratings))
assert np.isclose(tagged_ratings["weight"].sum(), len(ratings))
assert np.isclose(genre_table["weighted_share"].sum(), 1.0)
genre_table.head()
```

类型关联把 **100,000 条评分**展开成 **212,595 行**。例如一条属于三个标签的影片评分，会出现三次。

`many_to_many` 不自动检查重复关系，所以函数先检查电影类型组合唯一性。浮点权重和可能显示成99999.99999999999，用 `np.isclose` 核对，而不是强制逐位相等。

- `rating_mean`：标签内每条评分等权，评分多的影片贡献更多。
- `weighted_rating_mean`：每条评分按1/k计权。
- `equal_movie_weight_mean`：先算每片均分，再让电影等权。

| 类型 | 带该标签的影片数 | 全额关联评分行 | 分摊评分份额 | 分摊加权均分 | 电影等权均分 |
|---|---|---|---|---|---|
| Drama | 725 | 39,895 | 24.61% | 3.683 | 3.187 |
| Comedy | 505 | 29,832 | 18.29% | 3.350 | 3.001 |
| Action | 251 | 25,589 | 9.59% | 3.423 | 2.966 |
| Thriller | 251 | 21,872 | 9.40% | 3.496 | 3.137 |
| Romance | 247 | 19,461 | 8.10% | 3.582 | 3.244 |

上表按分摊评分份额取前五类，不是按最高均分挑选。所有 19 个类型均包含在聚合结果中；unknown 未删除。

**建议：** 把这些结果与目录及曝光结构对照；不能把类型均分差异解释成因果，也不能从评分份额推断市场需求。类型独立用户数不可跨类型相加。

## 第 9 步：先写 candidates.py，再分析候选榜

### 9.1 为什么考虑样本量

1条5星与200条平均4.3星的证据量不同。本例先要求至少30条，再使用收缩分，并同时展示原均分、数量、高分比例。

`收缩分 = (n×原均分 + m×全局均分)/(n+m)`。n小时更靠近全局均值，n大时更靠近该片均分；不是一律降低评分。全局均分来自全部有效评分，不能从候选或各片均分简单平均得到。

保存 `rating_lab/candidates.py` 的完整内容，然后才调用：

```python
# file: rating_lab/candidates.py
"""按评分量与收缩均分生成候选，所有数据通过参数传入。"""

import numpy as np
import pandas as pd


def make_candidate_table(ratings, movies, min_ratings=30, prior_strength=50):
    """按评分量门槛和收缩均分生成候选；所有输入显式传入。"""
    if ratings.empty or min_ratings < 1 or prior_strength < 0:
        raise ValueError("评分不能为空，门槛至少为1，收缩强度不能为负")
    if movies["movie_id"].duplicated().any():
        raise ValueError("电影ID必须唯一")
    if not ratings["movie_id"].isin(movies["movie_id"]).all():
        raise ValueError("有评分找不到对应电影")
    stats = ratings.assign(is_high=ratings["rating"].ge(4).astype(float)).groupby(
        "movie_id", as_index=False).agg(
            rating_count=("rating", "size"), raw_mean=("rating", "mean"),
            high_rating_ratio=("is_high", "mean"),
        )
    result = stats.loc[stats["rating_count"].ge(min_ratings)].merge(
        movies[["movie_id", "title"]], on="movie_id", how="left", validate="one_to_one",
    )
    overall_mean = float(ratings["rating"].mean())
    result["global_mean"] = overall_mean
    result["prior_strength"] = prior_strength
    result["shrunk_mean"] = (
        result["rating_count"] * result["raw_mean"] + prior_strength * overall_mean
    ) / (result["rating_count"] + prior_strength)
    result = result.sort_values(
        ["shrunk_mean", "rating_count", "movie_id"], ascending=[False, False, True],
    ).reset_index(drop=True)
    result["shrunk_rank"] = np.arange(1, len(result) + 1)
    return result
```

### 9.2 导入、调用并手算核对一行

```python
import rating_lab.candidates as candidates_module

candidates = candidates_module.make_candidate_table(ratings, movies, min_ratings=30, prior_strength=50)
first = candidates.iloc[0]
expected_score = (first["rating_count"] * first["raw_mean"] + 50 * ratings["rating"].mean()) / (first["rating_count"] + 50)
assert np.isclose(first["shrunk_mean"], expected_score)
candidates[["title", "rating_count", "raw_mean", "high_rating_ratio", "shrunk_mean", "shrunk_rank"]].head(10)
```

| 收缩排名 | 影片 | 评分数 | 原均分 | 收缩分 | 4/5 星比例 |
|---|---|---|---|---|---|
| 1 | Schindler's List (1993) | 298 | 4.466 | 4.332 | 88.9% |
| 2 | Shawshank Redemption, The (1994) | 283 | 4.445 | 4.308 | 90.1% |
| 3 | Casablanca (1942) | 243 | 4.457 | 4.299 | 88.9% |
| 4 | Star Wars (1977) | 583 | 4.358 | 4.293 | 85.9% |
| 5 | Usual Suspects, The (1995) | 267 | 4.386 | 4.251 | 86.9% |

本次共有 806 部影片达到 30 条门槛，全局均分为 3.52986。例如 A Close Shave 的原均分约 4.491、112 条评分，m=50 后约 4.194；Schindler's List 的原均分约 4.466、298 条评分，收缩后约 4.332。排序改变反映样本量与规则的影响，不能由此断言哪部片客观更好。

收缩分不是质量真值、显著性或线上效果证明，门槛与m都属于分析规则。

### 9.3 使用自己保存的函数做敏感性分析

```python
sensitivity_frames = []
for strength in [20, 50, 100]:
    scored = candidates_module.make_candidate_table(ratings, movies, min_ratings=30, prior_strength=strength).head(20).copy()
    sensitivity_frames.append(scored)
sensitivity_table = pd.concat(sensitivity_frames, ignore_index=True)
top_sets = {int(value): set(rows["movie_id"]) for value, rows in sensitivity_table.groupby("prior_strength")}
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

这是名单集合敏感性，不是独立样本确认，也不说明共同影片顺序相同。再亲手把30条门槛分别改为20和50，保留结果并解释边缘项为何变化。

## 第 10 步：从数字写到解释与建议

每条结论都按“现象及分母 → 有限解释 → 替代解释 → 行动候选 → 验证计划”展开。

| 实证观察 | 有限解释与替代解释 | 行动候选 | 还需什么验证 |
|---|---|---|---|
| 10→11 月评分用户 152→288，人均 67.79→83.26 | 记录量增长同时伴随人数与人均提交量增加；可能受样本组成和记录方式影响 | 先核查记录范围与参与机制，不直接归因于内容改善 | 活动日历、数据采集变更与曝光/播放日志 |
| 前169部占评分42.87%；755部长尾只占5.27% | 评分证据集中；小样本片的均分更容易波动 | 榜单同时展示量与分，不只按均分决策 | 曝光、观看及评价提交率，区分未被看见与反馈较低 |
| Drama/Comedy 分摊评分份额约24.61%/18.29% | 描述本样本的类型记录结构，不是市场需求；标签和目录构成也会影响份额 | 将评分结构与内容供给、曝光结构一起检查 | 同口径的目录、曝光和播放分母 |
| m20与m100的Top20共同17部 | 部分边缘候选依赖分析规则；名单稳定也不等于上线有效 | 将稳定且量足的对象列为编辑复核候选，记录边缘项 | 内容可用性、业务目标和预设的线上对照实验 |

这是历史公开样本的模拟分析。真实决策还需内容可用性、业务目标和后续验证，没有实验数据时不预写播放、留存或收入提升。

## 第 11 步：保存证据和自己的报告

```python
evidence = {name: json.loads(frame.to_json(orient="records")) for name, frame in {
    "monthly": monthly_table, "genre": genre_table,
    "top30_candidates": candidates.head(30),
    "sensitivity": sensitivity_table[["prior_strength", "movie_id", "title", "rating_count", "raw_mean", "shrunk_mean", "shrunk_rank"]],
    "top20_overlap": pd.DataFrame(overlap_rows),
}.items()}
evidence["quality"] = quality
evidence["concentration"] = concentration
evidence["source_sha256"] = SOURCE_SHA256
(OUTPUT / "evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("聚合证据保存到：", OUTPUT / "evidence.json")
```

在学习文件夹中新建 `MY_ANALYSIS.md`：依次写任务、来源范围、质量处理、指标方法、四个问题的结果、建议与验证、限制与复现。每个问题保留一张表或图、一条有数字的观察、一条替代解释。

源码是自己创建的 `rating_lab/*.py`；输入是本地原包；输出是聚合JSON和SVG。不要发布ZIP、行级评分或逐用户输出；Notebook提交前清空输出。

## 第 12 步：理解修改文件和导入缓存

现在的顺序一直是“完整源码 → 保存文件 → import模块 → 模块.函数(输入)”。`monthly_module` 是模块，`monthly_table` 是结果表。

第一次保存后正常导入；如果你改了已经导入的文件，单纯再次 `import` 不会自动刷新旧模块。可以重启内核再从头运行；或按下面完整代码重新加载模块并计算：

```python
import importlib

importlib.reload(monthly_module)
monthly_table = monthly_module.make_monthly_table(ratings)
```

重新加载模块不会自动改变已经生成的 `monthly_table`，所以还要重新调用函数。即使没有修改文件，运行上面这格也会得到同样的月度结果。

如果导入路径指向其他同名包，重启内核并确认工作目录，不通过改 `sys.path` 掩盖目录问题。本教程每个模块的代码都完整给出，不引用未展示的项目函数。

### 最终检查

- [ ] 第一步已经自己建立rating_lab和__init__.py，读取数据前确认包路径。
- [ ] 每个模块都先保存完整代码，再导入调用；没有在分析结束后才建包。
- [ ] 读取、质量检查、日期、类型拆解和所有计算可从源码追溯。
- [ ] 理解分母、完整月、关联粒度、权重守恒和收缩的限制。
- [ ] 复制文件代码时没有遗漏导入或函数体，文件扩展名确实是.py。
- [ ] 全部文件保存后，重启内核能够从头运行。
- [ ] 报告有证据、替代解释和待验证建议。

学习只需要本地ZIP、标准库与numpy/pandas/matplotlib。没有自动下载或项目安装前提；现有仓库的 [参考报告](../reports/analyst/ANALYSIS_REPORT.md) 与 [聚合指标](../reports/analyst/metrics.json) 仅用于核对，学习代码不调用它们。

数据使用GroupLens单独许可，代码许可不覆盖源数据。引用：Harper & Konstan (2015), *The MovieLens Datasets: History and Context*. [DOI: 10.1145/2827872](https://doi.org/10.1145/2827872).
