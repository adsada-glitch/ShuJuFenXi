# MovieLens Rating Lab：电影评分的时间验证与偏差分析

**学习目标：能独立设计一个可信的建模实验，并解释模型为什么有效、何时失效。**

核心问题：用户和电影的评分偏置，能否改善未来记录评分的预测？进一步加入矩阵分解后，改善是否稳定、对冷门电影是否仍成立？

适合已有 Python / 数据分析基础，想练统计、建模和工程规范的人。初版提供跑通的基线、评估和测试；矩阵分解与跨时间复验由你完成。

## 先跑起来

在仓库根目录执行（Python 3.11+）：

```powershell
cd MovieLensRatingLab
python -m venv .venv
# Windows，直接使用虚拟环境 Python，无需修改脚本执行策略
.venv\Scripts\python -m pip install -e .
.venv\Scripts\python -m rating_lab run
.venv\Scripts\python -m unittest discover -s tests -v
```

macOS / Linux：创建环境后，将上述 `.venv\Scripts\python` 换成 `.venv/bin/python`。
已激活环境时，统一使用：

```bash
python -m pip install -e .
python -m rating_lab run
python -m unittest discover -s tests -v
```

首次运行从官方站点下载约 5 MB 原包，校验固定 SHA-256；不需要 API Key。数据保存在被 Git 忽略的 `data/`。默认执行 2,000 次固定种子的用户簇 bootstrap。聚合报告写入 `reports/`。

想自己做 EDA：`python -m pip install -e ".[notebook]"`，再运行 `python -m jupyterlab`，打开 [探索练习本](notebooks/01_explore.ipynb)。

## 你能练到什么

| 能力 | 具体任务 | 验收依据 |
|---|---|---|
| 数据审计 | 校验来源、重复、评分范围、时间分布 | 可复现审计与数据说明 |
| 实验设计 | 全局时间切分，训练统计定义流行度 | 同时间戳不跨集，分组无未来信息 |
| 统计推断 | 按用户成对 bootstrap 比较误差 | 解释区间的条件与未覆盖的不确定性 |
| 建模 | 均值 → 电影偏置 → 用户+电影偏置 → 自己实现 MF | 验证集调参、固定测试协议、冷启动回退 |
| 工程 | 包结构、CLI、测试、CI、版本化实验记录 | 新环境可运行，边界测试通过 |
| 分析表达 | 分组误差、失败案例、反例与外推限制 | 写出自己的 findings，而非只报最低 RMSE |

## 先从这三个文件开始

1. [四周学习路线](docs/LEARNING_PATH.md)：阶段成果与建议 commit。
2. [基线报告](reports/BASELINE_REPORT.md)：实跑结果与第一项分析作业。
3. [五个实验](docs/EXPERIMENTS.md)：假设、对照、指标与失败条件。

![模型基线](reports/figures/model_comparison.svg)

**你的第一个提交**：完成 notebook 的审计练习，建立 `docs/MY_FINDINGS.md`，回答“为什么按全局时间切分时，很多测试用户在训练集中没出现过？”再用覆盖率和误差切片支持你的解释。

## 实验协议

- 使用 **MovieLens 100K 固定历史版本**。按评分时间近似 70/15/15 切分，时间戳相同的记录放在同一集合。
- 三个基线分别在验证集选择正则化；冻结后用训练+验证集重拟合，一次比较最终测试集。
- `global`：训练全局均分；`movie`：全局均分 + 收缩后的电影偏置；`user_movie`：再加入收缩后的用户偏置。预测裁剪到 1–5。
- 各模型用同一训练全局均值；偏置最小化平方误差加 L2 正则，交替更新 20 次。不同正则化为 `[1, 5, 10, 25, 50]`，都仅看验证误差选择。
- 主要指标 RMSE，辅助指标 MAE。预设统计比较为 `user_movie − movie`；同一测试用户的全部评分一起成对重采样，报告 rating-weighted RMSE 差的 95% 百分位区间。
- 冷启动不删除：未知实体的偏置回退为 0。分组按最终训练数据中电影评分数分为 unseen、1–20、21–100、>100，并报告已知/未知用户覆盖率。
- 初版报告已包含测试结果。后续改进请用预先固定的新时间窗口做确认，避免反复在同一测试集上调参。

## 数据与解释边界

来源：[GroupLens 100K 页面](https://grouplens.org/datasets/movielens/100k/)、[官方 README 与许可](https://files.grouplens.org/datasets/movielens/ml-100k-README.txt)。

100,000 条评分、943 位用户、1,682 部电影；数据来自 1997–1998 年，保留至少 20 条评分且人口信息完整的用户。项目只读取评分，不需要人口信息。这是小规模历史教学实验，不代表今天的电影市场。

评分是主动记录的、有选择的样本；时间戳是评分提交时间。**预测评分误差不等于线上推荐质量，也不能证明推荐带来观看或收入增长。**

数据受 GroupLens 单独条款约束：本仓库不再分发原包、行级数据、模型参数或逐用户预测；运行时从官方获取。`LICENSE` 只授权本项目代码和原创文档，不覆盖 MovieLens 数据。正式使用前请阅读其完整条款。

引用：F. Maxwell Harper and Joseph A. Konstan. 2015. *The MovieLens Datasets: History and Context*. ACM TIIS 5(4), Article 19. DOI: [10.1145/2827872](https://doi.org/10.1145/2827872).

## 文件导航

```text
MovieLensRatingLab/
  src/rating_lab/        # 数据、基线、bootstrap、CLI 与报告
  tests/test_core.py    # 时间边界、冷启动、簇重采样等关键测试
  notebooks/           # 可动手修改的 EDA 练习本
  docs/                # 学习路线、实验设计
  reports/             # 聚合指标、报告、图表
  pyproject.toml       # 直接依赖固定版本与可编辑安装
```

仓库根目录的 `.github/workflows/movielens-rating-lab.yml` 对本项目运行边界测试，不需要下载数据。直接依赖固定版本，实际 Python/包版本记录在 `reports/metrics.json`；未提供跨平台完整锁文件。要修改依赖时，用独立环境验证并记录版本差异。
