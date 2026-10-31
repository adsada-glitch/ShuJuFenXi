# 完整学习过程：从运行项目到独立完成电影评分实验

这是一份按顺序带做的教程。你不用在几份路线图之间切换：从第 0 步开始，完成一节的检查，再进入下一节。`reports/BASELINE_REPORT.md` 是程序生成的结果参考，Notebook 是执行代码的工作区，本文件负责全部学习顺序。

项目要回答的是：**用历史上已经记录的电影评分，预测后续记录的评分时，加入用户偏置能带来多少改善？这种改善对冷启动、冷门电影和不同时期是否一样？**

一行数据是一位用户对一部电影提交的一条 1–5 星评分。没有评分的用户电影组合不是 0 分，也不能直接当作不喜欢。这里做的是评分预测；没有曝光、点击或随机分配数据，不能据此证明推荐系统提高点击率。

## 先看全程

| 顺序 | 你实际要做的事 | 完成后留下什么 | 建议用时 |
|---|---|---|---|
| 0 | 建好环境，运行现有基线 | 成功运行记录 | 30–60 分钟 |
| 1 | 建立唯一的代码工作区 | 可连续运行的 Notebook | 15 分钟 |
| 2 | 审计数据，认识评分和时间 | `audit.json`、趋势图 | 1–2 小时 |
| 3 | 手动检查全局时间切分 | `split.json`、时间顺序断言 | 1 小时 |
| 4 | 用小例子算懂三个模型 | 手算与代码核对 | 1–2 小时 |
| 5 | 只在验证集比较模型、调参 | `validation_baselines.json` | 1–2 小时 |
| 6 | 冻结参数，理解最终重训 | `coverage.json`、分组指标 | 1–2 小时 |
| 7 | 比较差值和统计不确定性 | `bootstrap_validation.json` | 1–2 小时 |
| 8 | 做跨时间复验 | `rolling_validation.json` | 1–2 小时 |
| 9 | 选做：实现并检验矩阵分解 | MF 模型、验证结果 | 3–6 小时 |
| 10 | 理解测试、CI 与提交边界 | 一次有意义的代码提交 | 1 小时 |
| 11 | 写出自己的完整结论 | `docs/MY_FINDINGS.md` | 1–2 小时 |

上面的时间只是参考。完成 0–8、10–11 步就构成一个完整分析项目；第 9 步是建模进阶，不是开始分析前必须跨过的门槛。

**三种数据范围始终分清：**

| 名称 | 行数 | 允许做什么 |
|---|---:|---|
| `train` | 69,997 | 拟合开发模型、统计验证阶段的电影流行度和 ID 可见性 |
| `validation` | 15,003 | 比较方案、选择参数、做开发诊断 |
| `test` | 15,000 | 复现已公开的基准比较；不参与调参 |
| `final_train = train + validation` | 85,000 | 参数冻结后重拟合；定义测试阶段的 ID 可见性和电影流行度 |

仓库已经公开当前 `test` 的基线结果，因此后续在这段数据上改模型、再比较，属于公开基准上的探索。你完全可以用它学习，但不能说它仍是从未看过的独立确认数据。需要独立确认时，另行预留未查看的数据并先固定方案；滚动验证检验稳定性，不会凭空产生新的独立样本。

---

## 第 0 步：把项目跑起来

### 0.1 明确目录

以下终端命令默认使用 **Windows PowerShell**。仓库目录叫 `ShuJuFenXi`，项目目录是里面的 `MovieLensRatingLab`。

还没有本地仓库时，在你准备保存项目的目录运行：

```powershell
git clone https://github.com/adsada-glitch/ShuJuFenXi.git
cd ShuJuFenXi
```

已经有本地仓库时，进入那个目录；先执行 `git status` 查看是否有自己的未提交修改，再用正常 Git 流程同步。不要为了照教程重置或覆盖自己的文件。

从仓库目录进入项目并核对文件：

```powershell
cd MovieLensRatingLab
Get-Location
Test-Path .\pyproject.toml
Test-Path .\src\rating_lab\models.py
```

最后两条都应输出 `True`。后面的安装命令必须在这个项目目录中运行。

### 0.2 建立环境

```powershell
py -0p
py -3.12 --version
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[notebook]"
.\.venv\Scripts\python.exe -c "import sys, rating_lab; print(sys.executable); print(rating_lab.__file__)"
```

项目声明支持 Python 3.11+，本教程和 CI 统一用已验证的 **Python 3.12**。`py -0p` 列出 Windows 已安装解释器；没有 3.12 时先准备对应解释器，再继续，不要让命令意外使用另一版本。若系统没有 `py` 启动器，但 `python --version` 已确认是 3.12，可用 `python -m venv .venv` 创建环境。

最后命令打印的第一个路径应在本项目的 `.venv` 中，第二个应指向本项目 `src/rating_lab/__init__.py`。`-e` 表示可编辑安装，之后修改 `src/` 的代码不用每次重装。

这里直接调用虚拟环境 Python，不依赖 PowerShell 激活脚本，也不需要修改系统执行策略。macOS / Linux 用 `python3.12 -m venv .venv` 创建环境，用 `.venv/bin/python` 代替 `.\.venv\Scripts\python.exe`。

### 0.3 运行测试，再复现一次初版

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m rating_lab download
.\.venv\Scripts\python.exe -m rating_lab run
```

预期：12 项测试通过；下载命令显示 `Verified 100,000 ratings`；分析命令生成 `reports/BASELINE_REPORT.md`、`reports/metrics.json` 和 `reports/figures/`。

参考测试误差，允许末位浮点差异：

| 模型 | Test RMSE | Test MAE |
|---|---:|---:|
| `global` | 1.1296 | 0.9585 |
| `movie` | 1.0295 | 0.8333 |
| `user_movie` | 1.0115 | 0.8091 |

这一步只证明环境能跑通。你后续的调参代码直接使用 `train` 和 `validation`，不要用反复运行 `rating_lab run` 代替开发评估，因为 `run` 会自动显示测试结果并重写基线报告。

**本节完成条件：** 能说清代码、原始数据、生成结果分别在哪；12 项测试通过；成功运行完整基线一次。

---

## 第 1 步：建立连续的学习工作区

### 1.1 启动 Notebook

在项目目录的终端执行：

```powershell
.\.venv\Scripts\python.exe -m ipykernel install --user --name movielens-rating-lab --display-name "MovieLens Rating Lab"
.\.venv\Scripts\python.exe -m jupyterlab
```

打开 `notebooks/01_explore.ipynb`，选择 **MovieLens Rating Lab** 内核。这个 Notebook 只提供空白工作区；后面的 Python 代码块按顺序各放入一个新单元格。

**运行规则：** 标记为 `powershell` 的块在终端运行；标记为 `python` 的块在同一个 Notebook 内核依次运行。不要把 Python 代码逐行粘贴到 PowerShell。重启内核后，使用 “Restart Kernel and Run All Cells” 从头重跑，避免依赖以前残留的变量。

### 1.2 运行初始化单元格

```python
import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from rating_lab.data import PROJECT_ROOT, SOURCE_SHA256, load_ratings, temporal_split
from rating_lab.models import BiasModel
from rating_lab.bootstrap import paired_user_bootstrap

print(sys.executable)
print(PROJECT_ROOT)
OUTPUT = PROJECT_ROOT / "reports" / "learning"
OUTPUT.mkdir(parents=True, exist_ok=True)

def save_json(name, value):
    (OUTPUT / name).write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

def metrics(y_true, prediction):
    residual = np.asarray(y_true) - np.asarray(prediction)
    return {"rmse": float(np.sqrt(np.mean(residual ** 2))),
            "mae": float(np.mean(np.abs(residual)))}

ratings = load_ratings()
train, validation, test = temporal_split(ratings)
print("Loaded:", len(ratings), "ratings")
```

`PROJECT_ROOT` 来自包文件位置，不依赖 Notebook 当前工作目录，所以输出始终写进本项目 `reports/learning/`。这里的 `metrics()` 与正式流水线使用同一公式；不导入报告模块，避免其绘图后端设置影响 Notebook 显示。不要将自己的实验输出覆盖到 `reports/metrics.json`，后者保留初版参考值。

**本节产出：** 一个能重新从头运行的 Notebook；后面所有单元格共享这里的变量和导入。

---

## 第 2 步：先审计数据，再画图

打开 [data.py](../src/rating_lab/data.py) 的 `load_ratings()`，按“下载 → 哈希校验 → 读取评分 → 数据检查”的顺序读。无需先读网络下载的每个细节，先弄懂它保证了什么。

| 字段 | 含义 | 不能误解成什么 |
|---|---|---|
| `user_id` | 匿名用户标识 | 数值大小不是年龄、活跃度或相似度 |
| `movie_id` | 电影标识 | 数值大小不是发行顺序或质量 |
| `rating` | 1–5 星评分 | 未评分不能补成 0 星 |
| `timestamp` | 评分提交的 Unix 秒时间戳 | 不是观影时间、曝光时间或发行时间 |

### 2.1 生成可复核的审计记录

```python
rating_time = pd.to_datetime(ratings["timestamp"], unit="s", utc=True)
audit = {
    "rows": int(len(ratings)),
    "users": int(ratings["user_id"].nunique()),
    "movies": int(ratings["movie_id"].nunique()),
    "missing_cells": int(ratings.isna().sum().sum()),
    "duplicate_user_movie_pairs": int(ratings.duplicated(["user_id", "movie_id"]).sum()),
    "rating_min": int(ratings["rating"].min()),
    "rating_max": int(ratings["rating"].max()),
    "start_utc": rating_time.min().isoformat(),
    "end_utc": rating_time.max().isoformat(),
    "source_sha256": SOURCE_SHA256,
}
assert (audit["rows"], audit["users"], audit["movies"]) == (100000, 943, 1682)
assert audit["missing_cells"] == audit["duplicate_user_movie_pairs"] == 0
assert ratings["rating"].between(1, 5).all()
print(json.dumps(audit, ensure_ascii=False, indent=2))
save_json("audit.json", audit)
```

每条检查对应一个风险：缺失会影响训练，重复组合可能造成重复计权，越界评分可能是解析错误，时间范围决定结论能外推到哪里。ID 是类别编码，不应直接当作有序数值特征输入普通线性回归。

### 2.2 只用开发数据画时间趋势

```python
development = pd.concat([train, validation], ignore_index=True)
daily = (
    development.assign(day=pd.to_datetime(development["timestamp"], unit="s", utc=True).dt.floor("D"))
    .groupby("day")["rating"]
    .agg(n="size", mean="mean")
)
fig, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
axes[0].plot(daily.index, daily["n"])
axes[0].set_ylabel("Observed ratings / day")
axes[1].plot(daily.index, daily["mean"])
axes[1].set_ylabel("Mean observed rating")
fig.tight_layout()
fig.savefig(OUTPUT / "development_trends.svg", metadata={"Date": None})
plt.show()
```

不能把某天均分升高直接解释成“电影变好了”。至少还有用户组成、被评分电影组成和每天评分数不同这些替代解释。先在 Notebook Markdown 单元格写一个观察、两个解释，暂不下因果结论。

**本节完成条件：** 产出 `audit.json` 和 `development_trends.svg`；解释为什么数据没有缺失，也不等于它代表所有用户。官方样本保留至少 20 条评分且人口信息完整的用户，本项目只读取评分。

---

## 第 3 步：理解时间切分和“未来信息”

打开 [data.py](../src/rating_lab/data.py) 的 `temporal_split()`。程序先排序，用大约 70% 和 85% 位置处的时间戳作边界，再用时间戳过滤。边界同一时刻的评分统一进入后一个集合，因此不是简单的三段 `iloc`。

### 3.1 用断言检查，而不是凭感觉相信切分

```python
assert train["timestamp"].max() < validation["timestamp"].min()
assert validation["timestamp"].max() < test["timestamp"].min()
assert len(train) + len(validation) + len(test) == len(ratings)

split_record = {}
for name, part in [("train", train), ("validation", validation), ("test", test)]:
    split_record[name] = {
        "rows": int(len(part)),
        "start_utc": pd.to_datetime(part["timestamp"].min(), unit="s", utc=True).isoformat(),
        "end_utc": pd.to_datetime(part["timestamp"].max(), unit="s", utc=True).isoformat(),
    }
print(pd.DataFrame(split_record).T)
save_json("split.json", split_record)
```

预期行数为 **69,997 / 15,003 / 15,000**。如果你得到 70,000 / 15,000 / 15,000，先确认是否把同一时间戳拆开了；不要把比例“更整齐”误认为实验更正确。

### 3.2 弄懂什么阶段能使用什么统计量

- 验证一个只用 `train` 拟合的模型时，新用户、新电影与流行度都以 `train` 为准。
- 最终参数冻结后，允许 `train + validation` 重拟合；评价 `test` 时才以这 85,000 条为准。
- 不能先从所有数据提取用户电影映射、评分均值和电影流行度，再假装训练时不知道未来。
- 使用未来时间戳来确定离线评估的边界不同于使用未来评分来拟合；此处切分不根据评分值挑样本。

**本节小练习：** 在一份本地临时数据上把 `validation.rating` 全改成 1，再运行 `temporal_split()`。边界应不受评分值影响。不要修改正式 `ratings` 或提交伪造数据。

**完成条件：** 产出 `split.json`；能分别解释“随机划分模拟什么”和“时间划分模拟什么”，并知道本项目选了后者。

---

## 第 4 步：手算三个模型，再读实现

打开 [models.py](../src/rating_lab/models.py)。先看 `predict()` 的最后一行，再回头看 `fit()`，你会更容易理解每一步训练在为预测准备什么。

记 `mu` 为训练评分均值，`b_u` 为用户偏置，`b_i` 为电影偏置。这里的“偏置”表示相对均分的偏移，不是社会公平意义上的歧视结论。

| `mode` | 裁剪前的预测 | 学到什么 |
|---|---|---|
| `global` | `mu` | 所有记录使用同一个均分 |
| `movie` | `mu + b_i` | 电影的平均偏高或偏低倾向 |
| `user_movie` | `mu + b_u + b_i` | 同时考虑用户评分宽松程度与电影倾向 |

预测都裁剪到 `[1, 5]`。`mu` 固定为本次拟合数据的均值；训练最小化**裁剪前**预测的残差平方和，加 `strength * sum(bias**2)`。这里不是先除以评分数的 MSE；改变数据量时，相同 `strength` 的相对收缩效果也会变化。

### 4.1 一个能算清楚的电影偏置

```python
toy = pd.DataFrame({
    "user_id": [1, 1, 2, 2],
    "movie_id": [10, 20, 10, 20],
    "rating": [5, 3, 4, 2],
    "timestamp": [1, 2, 3, 4],
})
toy_model = BiasModel(mode="movie", strength=2).fit(toy)
query = pd.DataFrame({"user_id": [1, 999, 999], "movie_id": [10, 20, 999]})
toy_prediction = toy_model.predict(query)
print(toy_prediction)
assert np.allclose(toy_prediction, [4.0, 3.0, 3.5])
```

手算：全局均分是 `3.5`。电影 10 的残差为 `1.5` 和 `0.5`，所以偏置是 `(1.5 + 0.5) / (2 + 2) = 0.5`，预测 `4.0`；电影 20 的偏置是 `-0.5`；未知电影回退到 `3.5`。

一般的电影更新公式为：

```text
b_i = sum(r_ui - mu - b_u) / (n_i + strength)
b_u = sum(r_ui - mu - b_i) / (n_u + strength)
```

`user_movie` 交替更新两类偏置 20 次。`movie` 不更新用户偏置。`pd.factorize` 将训练 ID 变成紧凑整数位置，`np.bincount` 按这些位置计算计数和残差之和，最后又用真实 ID 建回映射。

### 4.2 冷启动回退必须有定义

| 当前记录 | `user_movie` 的裁剪前回退 |
|---|---|
| 用户和电影都见过 | `mu + b_u + b_i` |
| 新用户、已见电影 | `mu + b_i` |
| 已见用户、新电影 | `mu + b_u` |
| 两者都新 | `mu` |

**亲手修改：** 只在 toy 实验中把 `strength=2` 改成 `20`，观察电影偏置是否更接近 0，再改成 0。解释“收缩”减少了什么，也可能抹去了什么。不要通过删掉未知 ID 来提高指标。

**完成条件：** 手算与代码一致；能找到代码中固定均值、交替更新、未知 ID 填 0、裁剪预测这四处实现。

---

## 第 5 步：在验证集上比较和选参数

先写评价目标，再计算成绩。RMSE 对大误差更敏感，MAE 更接近平均绝对偏差。本项目以 RMSE 为主要选择指标，MAE 为辅助诊断；看到结果后不能临时更换主指标来宣布某模型获胜。

```text
RMSE = sqrt(mean((真实评分 - 预测评分)^2))
MAE  = mean(abs(真实评分 - 预测评分))
```

### 5.1 保留全部候选结果

```python
grid = [1.0, 5.0, 10.0, 25.0, 50.0]
trials = []
for mode in ["global", "movie", "user_movie"]:
    strengths = [0.0] if mode == "global" else grid
    for strength in strengths:
        model = BiasModel(mode=mode, strength=strength).fit(train)
        row = {"mode": mode, "strength": strength,
               **metrics(validation["rating"], model.predict(validation))}
        trials.append(row)

trial_table = pd.DataFrame(trials)
best_rows = trial_table.loc[trial_table.groupby("mode")["rmse"].idxmin()]
selected = {row["mode"]: float(row["strength"]) for row in best_rows.to_dict("records")}
dev_models = {mode: BiasModel(mode=mode, strength=value).fit(train)
              for mode, value in selected.items()}
dev_predictions = {mode: model.predict(validation) for mode, model in dev_models.items()}
print(trial_table.to_string(index=False))
print("Selected:", selected)
save_json("validation_baselines.json", {"trials": trials, "selected": selected})
```

参考：`movie` 的最佳 `strength=5`，验证 RMSE 约 `1.0253`；`user_movie` 的最佳 `strength=1`，验证 RMSE 约 `1.0279`。**开发验证上，用户偏置模型并没有赢过电影偏置模型。** 这与初版测试集上的排序不同，正好用来学习“单次成绩”和“稳定规律”的区别。

### 5.2 自己画一张参数曲线

```python
fig, ax = plt.subplots(figsize=(7, 4))
for mode in ["movie", "user_movie"]:
    rows = trial_table[trial_table["mode"] == mode]
    ax.plot(rows["strength"], rows["rmse"], marker="o", label=mode)
ax.set(xscale="log", xlabel="Regularization strength", ylabel="Validation RMSE")
ax.legend()
fig.tight_layout()
fig.savefig(OUTPUT / "regularization.svg", metadata={"Date": None})
plt.show()
```

### 5.3 做第一个单因素实验

先在 Markdown 单元格写下：“我预期收缩主要帮助训练评分少的电影。”然后固定 `mode="movie"`，只改变 `strength`；用 `train.movie_id.value_counts()` 将验证评分分成 0、1–20、21–100、>100 四组，再比较不同参数下的误差。

第 6 步提供现成的分组函数，你完成那一步后可以回到这里重复实验。不要同时换数据划分、模型和正则化，否则无法说明差值来自哪里。

**完成条件：** 产出全部候选表和参数曲线；能解释为什么不能根据当前测试成绩反过来决定选择哪个 `strength`。

---

## 第 6 步：区分开发诊断与最终重训

### 6.1 冻结参数，用 85,000 条重训

```python
final_train = pd.concat([train, validation], ignore_index=True)
assert len(final_train) == 85000
final_models = {mode: BiasModel(mode=mode, strength=value).fit(final_train)
                for mode, value in selected.items()}
final_predictions = {mode: model.predict(test) for mode, model in final_models.items()}
final_scores = {mode: metrics(test["rating"], pred) for mode, pred in final_predictions.items()}
print(pd.DataFrame(final_scores).T)
```

这一步复现已公开的测试比较：参数来自第 5 步，测试评分没有参与拟合。重训会重新计算 `mu` 和偏置，所以不要期待同一记录在 `dev_models` 和 `final_models` 下预测完全一样。

### 6.2 将覆盖率的分母写出来

```python
def coverage_record(fit_data, evaluation):
    known_user = evaluation["user_id"].isin(fit_data["user_id"])
    known_movie = evaluation["movie_id"].isin(fit_data["movie_id"])
    unique_users = evaluation[["user_id"]].drop_duplicates()
    return {
        "evaluation_ratings": int(len(evaluation)),
        "evaluation_unique_users": int(len(unique_users)),
        "known_user_rating_fraction": float(known_user.mean()),
        "known_movie_rating_fraction": float(known_movie.mean()),
        "known_user_unique_user_fraction": float(unique_users["user_id"].isin(fit_data["user_id"]).mean()),
        "known_user_ratings": int(known_user.sum()),
        "both_known_rating_fraction": float((known_user & known_movie).mean()),
    }

coverage = {
    "validation_given_train": coverage_record(train, validation),
    "test_given_final_train": coverage_record(final_train, test),
}
print(pd.DataFrame(coverage).T)
save_json("coverage.json", coverage)
assert np.isclose(coverage["test_given_final_train"]["known_user_rating_fraction"], 2514 / 15000)
assert np.isclose(coverage["test_given_final_train"]["known_user_unique_user_fraction"], 91 / 226)
```

**16.76% = 2,514 / 15,000，分母是评分条数；40.27% = 91 / 226，分母才是测试集的独立用户数。** 不能把前一个比例说成“只有 16.8% 的测试用户见过”。

在全局时间切分下，某人即使在整个数据里有 20 条以上评分，也可能全部提交于切分边界之后，因此在早期训练集里仍是新用户。评分提交常集中在一段时间内，这是需要核查的现象；不是仅凭此比例就能证明的机制。

### 6.3 写一个能反复使用的分组函数

```python
def slice_scores(fit_data, evaluation, predictions):
    movie_counts = evaluation["movie_id"].map(fit_data["movie_id"].value_counts()).fillna(0).to_numpy()
    popularity = np.select(
        [movie_counts == 0, movie_counts <= 20, movie_counts <= 100],
        ["unseen", "tail (1-20)", "middle (21-100)"], default="head (>100)",
    )
    known_user = evaluation["user_id"].isin(fit_data["user_id"]).to_numpy()
    known_movie = evaluation["movie_id"].isin(fit_data["movie_id"]).to_numpy()
    masks = {label: popularity == label for label in
             ["unseen", "tail (1-20)", "middle (21-100)", "head (>100)"]}
    masks.update({
        "both_known": known_user & known_movie,
        "new_user_only": ~known_user & known_movie,
        "new_movie_only": known_user & ~known_movie,
        "both_new": ~known_user & ~known_movie,
    })
    rows = []
    for label, mask in masks.items():
        if not mask.any():
            continue
        for mode, prediction in predictions.items():
            rows.append({"slice": label, "model": mode,
                         "n_ratings": int(mask.sum()),
                         "n_users": int(evaluation.loc[mask, "user_id"].nunique()),
                         **metrics(evaluation.loc[mask, "rating"], np.asarray(prediction)[mask])})
    return pd.DataFrame(rows)

validation_slices = slice_scores(train, validation, dev_predictions)
test_slices = slice_scores(final_train, test, final_predictions)
print(validation_slices.to_string(index=False))
save_json("cold_start_slices.json", {
    "validation": validation_slices.to_dict("records"),
    "published_test": test_slices.to_dict("records"),
})
```

前四个流行度组彼此互斥，后四个冷启动组也彼此互斥，但两套分组相互重叠；不要把八组样本数相加当成总量。所有预测数组必须与 `evaluation` 的原始行顺序一致，不能单独排序或过滤后直接配对。

现在可回到第 5.3 步，给不同 `strength` 重新生成验证预测，再传入本函数。一次只改变正则化强度。

**完成条件：** 覆盖率两个分母都能算对；输出分组样本数与误差；能解释为什么总体误差改善不等于每个群体都改善。

---

## 第 7 步：比较模型差值，而非只比较小数点

打开 [bootstrap.py](../src/rating_lab/bootstrap.py)。同一个人的多条评分往往不独立，所以这里抽用户，再把抽中用户的全部评分一起带入；候选和基线始终使用相同的抽样。

### 7.1 先在验证集上计算

```python
validation_comparison = paired_user_bootstrap(
    y_true=validation["rating"],
    reference_predictions=dev_predictions["movie"],
    candidate_predictions=dev_predictions["user_movie"],
    user_ids=validation["user_id"],
    n_boot=2000, seed=42,
)
print(validation_comparison)
save_json("bootstrap_validation.json", validation_comparison)
assert validation_comparison["delta_rmse"] > 0
```

差值定义为 `RMSE(user_movie) - RMSE(movie)`：负数才是候选更好。验证差值约 `+0.0026`；本节不要把初版测试区间抄过来代替验证比较。

这里的验证集同时用于第 5 步的参数选择，因此本区间没有包含模型选择造成的不确定性，只作开发诊断，不能当作独立确认性的显著性证据。

### 7.2 再核对已经公开的测试比较

```python
published_comparison = paired_user_bootstrap(
    test["rating"], final_predictions["movie"], final_predictions["user_movie"],
    test["user_id"], n_boot=2000, seed=42,
)
print(published_comparison)
assert np.isclose(published_comparison["delta_rmse"], -0.0180234772, atol=1e-8)
```

参考测试差值 `-0.0180`，95% 百分位区间约 `[-0.0403, -0.0009]`。它条件于当前拟合模型、样本时期和按用户抽样的假设；不包含重训随机性、未来时间漂移，也未全面处理同一电影跨用户造成的依赖。区间没有跨 0 不等于收益足够大；跨 0 也不等于证明两模型相同。

### 7.3 区分“用户抽样单位”和“指标权重”

这个函数虽然抽用户，但每次仍把抽中用户的评分残差加在一起算 RMSE，因此活跃用户仍贡献更多记录。它不是“每位用户 RMSE 的简单平均”。亲手比较两种目标：

```python
error_frame = validation[["user_id"]].copy()
error_frame["squared_error"] = (validation["rating"].to_numpy() - dev_predictions["movie"]) ** 2
rating_weighted_rmse = float(np.sqrt(error_frame["squared_error"].mean()))
mean_user_rmse = float(np.sqrt(error_frame.groupby("user_id")["squared_error"].mean()).mean())
print({"rating_weighted_rmse": rating_weighted_rmse, "mean_user_rmse": mean_user_rmse})
```

这两个量回答不同问题；不要根据哪个更好看临时换评价目标。

**完成条件：** 写出差值方向、抽样单位、指标权重和区间未覆盖的风险各一句；解释验证排序和测试排序相反为何不能靠挑一个结果解决。

---

## 第 8 步：用滚动窗口检查结论是否稳定

这里先固定两种模型都用 `strength=5`，不在每个评价窗口调参，目的是隔离比较“增加用户偏置”的影响。你可以另做内层验证调参实验，但不能用当前外层评价窗口选择参数。

```python
dev_sorted = development.sort_values("timestamp", kind="stable").reset_index(drop=True)
rolling_rows = []
for fraction in [0.4, 0.6, 0.8]:
    cutoff = int(dev_sorted.iloc[int(len(dev_sorted) * fraction)]["timestamp"])
    end = cutoff + 14 * 24 * 60 * 60
    rolling_train = dev_sorted[dev_sorted["timestamp"] < cutoff]
    rolling_eval = dev_sorted[(dev_sorted["timestamp"] >= cutoff) & (dev_sorted["timestamp"] < end)]
    if rolling_train.empty or rolling_eval.empty:
        continue
    row = {
        "cutoff_utc": pd.to_datetime(cutoff, unit="s", utc=True).isoformat(),
        "last_rating_utc": pd.to_datetime(rolling_eval["timestamp"].max(), unit="s", utc=True).isoformat(),
        "n_train": int(len(rolling_train)), "n_evaluation": int(len(rolling_eval)),
        **coverage_record(rolling_train, rolling_eval),
    }
    for mode in ["movie", "user_movie"]:
        rolling_model = BiasModel(mode=mode, strength=5).fit(rolling_train)
        row[mode + "_rmse"] = metrics(rolling_eval["rating"], rolling_model.predict(rolling_eval))["rmse"]
    row["delta_rmse"] = row["user_movie_rmse"] - row["movie_rmse"]
    rolling_rows.append(row)

assert len(rolling_rows) == 3
print(pd.DataFrame(rolling_rows).to_string(index=False))
save_json("rolling_validation.json", rolling_rows)
```

每个窗口最多评价之后 14 天，数据末端可能使窗口变短，必须保留实际结束时间和样本数。窗口全部来自前 85% 开发数据，不触碰末段测试评分。

先回答三个问题，再写结论：差值方向是否一致？新用户评分比例是否变化？评分数相差很大的窗口是否同样可靠？这些窗口可能共享用户和电影，甚至重叠评分，并非独立重复实验，不能简单当作三份独立样本求显著性。

**完成条件：** 生成三个窗口的记录；如果优势反转，保留结果并分析适用范围，不通过换窗口把失败藏掉。

---

## 第 9 步：选做进阶——从偏置模型走到矩阵分解

完成前面的分析后再做这一节。偏置只能表达“用户普遍打分高”“电影普遍得分高”；矩阵分解增加用户向量 `p_u` 和电影向量 `q_i`，用内积表达用户与电影之间的交互：

```text
prediction = mu + b_u + b_i + dot(p_u, q_i)
```

下面是可运行的教学版本：先冻结已训练的用户电影偏置，再学习残差的低秩交互。它**不是**联合优化偏置和向量的完整 SVD 实现；把差异说清楚，比只贴一个模型名字更重要。

### 9.1 在 Notebook 新单元格运行模型定义

```python
class ResidualMF:
    def __init__(self, factors=8, epochs=10, learning_rate=0.005,
                 regularization=0.05, bias_strength=5.0, seed=42):
        self.factors = factors
        self.epochs = epochs
        self.learning_rate = learning_rate
        self.regularization = regularization
        self.bias_strength = bias_strength
        self.seed = seed

    def fit(self, frame):
        self.baseline = BiasModel(mode="user_movie", strength=self.bias_strength).fit(frame)
        self.users = {value: index for index, value in enumerate(frame["user_id"].unique())}
        self.movies = {value: index for index, value in enumerate(frame["movie_id"].unique())}
        u = frame["user_id"].map(self.users).to_numpy(dtype=int)
        i = frame["movie_id"].map(self.movies).to_numpy(dtype=int)
        y = frame["rating"].to_numpy(dtype=float)
        # 训练目标使用未裁剪的偏置预测，保持模型定义一致。
        offset = (self.baseline.mean_
                  + frame["user_id"].map(self.baseline.user_bias_).fillna(0).to_numpy()
                  + frame["movie_id"].map(self.baseline.movie_bias_).fillna(0).to_numpy())
        rng = np.random.default_rng(self.seed)
        self.P = rng.normal(0, 0.05, (len(self.users), self.factors))
        self.Q = rng.normal(0, 0.05, (len(self.movies), self.factors))
        self.loss_history = []
        for epoch in range(self.epochs):
            for index in rng.permutation(len(frame)):
                uid, mid = u[index], i[index]
                p, q = self.P[uid].copy(), self.Q[mid].copy()
                error = y[index] - offset[index] - p @ q
                self.P[uid] += self.learning_rate * (error * q - self.regularization * p)
                self.Q[mid] += self.learning_rate * (error * p - self.regularization * q)
            prediction = offset + np.sum(self.P[u] * self.Q[i], axis=1)
            objective = (0.5 * np.sum((y - prediction) ** 2)
                         + 0.5 * self.regularization
                         * (np.sum(np.bincount(u)[:, None] * self.P ** 2)
                            + np.sum(np.bincount(i)[:, None] * self.Q ** 2)))
            self.loss_history.append(float(objective))
            if not np.isfinite(objective):
                raise ValueError("MF diverged; reduce the learning rate")
        return self

    def predict(self, frame):
        offset = (self.baseline.mean_
                  + frame["user_id"].map(self.baseline.user_bias_).fillna(0).to_numpy()
                  + frame["movie_id"].map(self.baseline.movie_bias_).fillna(0).to_numpy())
        u = frame["user_id"].map(self.users).fillna(-1).to_numpy(dtype=int)
        i = frame["movie_id"].map(self.movies).fillna(-1).to_numpy(dtype=int)
        known = (u >= 0) & (i >= 0)
        interaction = np.zeros(len(frame))
        interaction[known] = np.sum(self.P[u[known]] * self.Q[i[known]], axis=1)
        return np.clip(offset + interaction, 1, 5)
```

每条记录的目标是 `0.5 * error**2 + 0.5 * regularization * (||p_u||² + ||q_i||²)`。每出现一条评分都施加一次收缩，因此上面总目标中的正则项按实体的训练出现次数加权。这个实现的正则化约定与第 4 步偏置模型不同，参数数值不能直接横比。

更新前复制 `p`、`q`，确保两条更新使用同一步的旧向量。新用户或新电影没有可学习的交互向量，只用已知偏置回退，不能将未知 ID `-1` 当作矩阵最后一行取值。

### 9.2 先做小规模检查，再训练真实数据

```python
mf_toy = ResidualMF(factors=2, epochs=3, seed=42).fit(toy)
assert np.isfinite(mf_toy.predict(query)).all()
assert np.all((mf_toy.predict(query) >= 1) & (mf_toy.predict(query) <= 5))
assert np.isclose(mf_toy.predict(query)[2], mf_toy.baseline.mean_)
mf_toy_again = ResidualMF(factors=2, epochs=3, seed=42).fit(toy)
assert np.allclose(mf_toy.predict(query), mf_toy_again.predict(query))
print("MF toy checks passed")
```

### 9.3 用验证集进行一次预算受限的比较

```python
from time import perf_counter

mf_rows = []
for factors in [4, 8]:
    start = perf_counter()
    mf = ResidualMF(factors=factors, epochs=10,
                    bias_strength=selected["user_movie"], seed=42).fit(train)
    pred = mf.predict(validation)
    mf_rows.append({"factors": factors, "epochs": 10, "seed": 42,
                    "learning_rate": 0.005, "regularization": 0.05,
                    "bias_strength": selected["user_movie"],
                    "seconds": perf_counter() - start,
                    "parameters": int(mf.P.size + mf.Q.size),
                    "training_objective": mf.loss_history,
                    **metrics(validation["rating"], pred)})
print(pd.DataFrame([{k: v for k, v in row.items() if k != "training_objective"} for row in mf_rows]))
save_json("mf_validation.json", mf_rows)
```

这段纯 NumPy 教学代码在 Python 循环里做 SGD，比优化过的库慢。先只跑这两个配置；更改维度、学习率、正则化时一次改变一个因素，再用预定的小搜索预算比较，不要无休止地追逐测试集成绩。

**结果怎么解释：** 如果 MF 没赢，检查训练目标是否下降、是否过拟合、新用户是否太多、交互项是否需要更长训练。不要直接断言“矩阵分解无效”，也不要为了让它赢而删掉冷启动评分。

**本节提交任务：** 理解后把类移到 `src/rating_lab/mf.py`。模块顶部补上 `import numpy as np` 和 `from .models import BiasModel`，因为独立模块不会继承 Notebook 的导入。随后在 Notebook 中用 `from rating_lab.mf import ResidualMF` 替换原类定义，重启内核并重跑 toy 检查与真实验证。

补充小数据、未知 ID、范围和重复性测试；验证至少两个维度并保留失败结果。若要把它接入正式 CLI，先读第 10 步的调用链，再另做一次可审查的代码修改。教程本身不会自动改动生产模型或报告。

---

## 第 10 步：把分析做成可以维护的工程

### 10.1 按调用顺序读代码

```text
python -m rating_lab run
    └─ __main__.py: main() 解析命令参数
        └─ pipeline.py: run()
            ├─ data.py: load_ratings() 获取并核验数据
            ├─ data.py: temporal_split() 划分时间段
            ├─ models.py: BiasModel.fit()/predict() 做验证搜索
            ├─ 参数冻结，train+validation 重拟合
            ├─ bootstrap.py: paired_user_bootstrap() 比较误差
            └─ pipeline.py: make_figures()/write_report() 写聚合结果
```

先在这些函数旁写自己的阅读笔记。不要逐行注释“这行加 1”，而应说明输入输出、关键假设和为什么不能改顺序。

### 10.2 读懂现有 12 项测试

打开 [test_core.py](../tests/test_core.py)，把测试分为：时间边界与同戳、基线与冷启动、评分范围与不读 holdout 标签、成对用户簇重采样与固定种子。

在 Notebook 中人为修改一个临时预测的评分标签，观察 `predict()` 是否变化；它不应读取评价集标签。若你实现 MF，优先测未知 ID 和小数据更新，不要只测试“某条真实数据 RMSE 小于一个神奇数字”。

终端验证命令：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

仓库的 GitHub Actions 在 Linux 和 Windows、Python 3.12 下安装项目并运行这些测试。**当前 CI 不下载真实数据、不执行整条分析流程，也不替代你对新实验的解释。** 新增 `mf.py` 后若没有写新测试，CI 绿色也不能证明 MF 已被验证。

### 10.3 确认提交边界

只发布聚合审计、聚合误差和原创说明；原包、行级评分、逐用户预测、训练向量不要入库。`data/` 已在 `.gitignore` 中，但 Notebook 输出仍需自己清理，不能以为 Git 忽略目录就能过滤单元格输出。当前单用户级 `error_frame` 仅用于本地计算，不保存明细。

**完成条件：** 你的新代码有相应边界验证；别人按 README 可运行；提交中没有原始数据、行级输出或模型参数。

---

## 第 11 步：写出属于你的项目报告

建立 `docs/MY_FINDINGS.md`，按下面结构填你实际观察到的结果。不要复制预期当结论，也不要用“模型效果很好”代替数字和适用范围。

```markdown
# 我的电影评分分析

## 1. 问题和评价目标
我预测什么？主要指标是什么？改进多大才值得进一步研究？

## 2. 数据和实验协议
数据版本/哈希、时间边界、训练/验证/最终重训范围、参数搜索预算。

## 3. 基线和开发结果
记录全部候选。验证和公开测试是否给出了相同排序？

## 4. 群体差异
新用户、新电影、冷门电影分别怎样？分母是评分还是用户？

## 5. 不确定性和跨时期表现
比较差值、区间、滚动窗口；区间未覆盖哪些风险？

## 6. 进阶实验（若完成）
MF的具体定义、验证结果、随机种子、时间成本、失败分析。

## 7. 结论与下一步
哪些观察支持假设，哪些反驳？能推广到哪里？下一次只改变什么？

## 8. 复现
提交号、Python/依赖版本、命令、聚合结果路径。
```

### 11.1 将完整学习过程提交到自己的分支

完成上面的 `MY_FINDINGS.md` 后，在 `MovieLensRatingLab` 项目目录执行以下终端命令；首次创建分支时使用一个尚不存在的名字：

```powershell
git switch -c learn/movielens-analysis
git status
# Notebook 里先 Clear Outputs，再保存，防止提交行级数据或残留输出。
git add notebooks/01_explore.ipynb reports/learning docs/MY_FINDINGS.md
git diff --cached --stat
git diff --cached --check
git commit -m "analysis: document temporal rating experiments and findings"
git push -u origin learn/movielens-analysis
```

只提交你确实完成的内容；实现 MF 时另选 `src/rating_lab/mf.py` 和相关测试加入提交。若分支已存在，使用 `git switch learn/movielens-analysis`，不必再次 `-c`。推送后在 GitHub 比较这个分支与 `main`，通过 Pull Request 展示你新增的实验和解释。

### 11.2 完成整个项目的验收表

- [ ] 重启内核后，从头运行 Notebook 不报错。
- [ ] 数据审计、时间切分、全部验证候选、分组误差都有可复核产物。
- [ ] 能手算一个电影偏置，并解释未知 ID 如何回退。
- [ ] 能正确区分 16.76% 的评分覆盖率和 40.27% 的用户覆盖率。
- [ ] 验证阶段的分组用 `train`，测试阶段的分组用 `final_train`。
- [ ] bootstrap 差值方向、抽样单位、指标权重解释清楚。
- [ ] 完成三个滚动窗口；失败或反转的结果也保留。
- [ ] 如完成 MF，记录实现约定、搜索预算、成本与新测试。
- [ ] 新结论未把已经公开的测试集说成从未看过的独立确认数据。
- [ ] 报告写出了你自己的解释、反例和限制，而非仅展示图表。
- [ ] 测试通过；提交内容没有原始数据和行级明细。

达到这些条件，你展示的就是一个可复现、可解释、有实验过程的数据分析项目。模型没有赢，也可以是一份合格而有价值的结果。

---

## 卡住时按这里排查

| 现象 | 先检查什么 | 处理方式 |
|---|---|---|
| `No module named rating_lab` | Notebook 内核与安装用的 Python 是否一致 | 回到 0.2 和 1.1，选择命名内核；确认 `rating_lab.__file__` |
| PowerShell 不识别 Python 语法 | 是否把 `python` 代码块粘进终端 | Python 块放 Notebook；终端只运行 `powershell` 块 |
| `NameError` | 是否跳过前面的单元格或重启过内核 | 从第 1.2 步顺序运行；不要靠重复定义同名变量补洞 |
| 图和 JSON 保存到奇怪目录 | 是否自己改成相对路径 | 保留 `OUTPUT = PROJECT_ROOT / "reports" / "learning"` |
| 下载或证书错误 | 网络和系统证书是否正常 | 下载器在 Windows 会尝试系统证书方案；保留 TLS 校验，不修改校验和 |
| 缓存哈希不符 | `data/ml-100k.zip` 是否完整或被改动 | 只删除这个已确认的缓存文件，然后重新下载；不要清空整个项目 |
| 评分数切分不等于整数百分比 | 是否存在边界同时间戳 | 以严格时间顺序为准，核对 69,997/15,003/15,000 |
| 16.8% 对不上 | 是否混用了 train/final_train 或评分/用户分母 | 对照第 6.2 步分别计算两种覆盖率 |
| MF 很慢或目标发散 | 是否扩大搜索、学习率过大 | 先跑 toy，再用两个小配置；目标不有限时减小学习率 |
| 无法向仓库推送 | Git 登录账户、权限、分支是否正确 | 查看 `git remote -v` 和 `git status`，按 GitHub 正常登录流程处理 |

## 数据来源与引用

数据与许可：[GroupLens MovieLens 100K](https://grouplens.org/datasets/movielens/100k/)、[官方 README](https://files.grouplens.org/datasets/movielens/ml-100k-README.txt)。源数据适用其单独条款，本项目 MIT 许可不覆盖它。

F. Maxwell Harper and Joseph A. Konstan. 2015. *The MovieLens Datasets: History and Context*. ACM TIIS 5(4), Article 19. [DOI: 10.1145/2827872](https://doi.org/10.1145/2827872).
