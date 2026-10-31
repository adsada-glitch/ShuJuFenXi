# MovieLens Rating Lab：电影评分的时间验证与偏差分析

用 MovieLens 100K 学习一个完整的数据分析过程：审计数据、设计时间验证、比较评分模型、分析冷启动和统计不确定性，最后写出可复现的结论。

## 从这里开始

**[打开《完整学习过程》](docs/LEARNING_GUIDE.md)**

这份教程是唯一的学习顺序入口。按第 0–11 步依次完成，每一步都有操作代码、预期结果、完成条件和产物。覆盖环境安装、数据审计、模型手算、验证调参、最终重训、分组误差、bootstrap、滚动验证、选做矩阵分解，以及测试和 Git 提交。文末提供排错表。

[Notebook](notebooks/01_explore.ipynb) 是执行教程代码的空白工作区；[基线报告](reports/BASELINE_REPORT.md) 是程序生成的参考结果；二者不再另设学习路线。

## 已有基础设施

- 三个可运行基线：`global`、`movie`、`user_movie`，参数只用验证集选择。
- 按全局评分时间近似 70/15/15 切分，同时间戳不跨集合。
- 参数冻结后用 train+validation 重拟合，报告测试 RMSE / MAE、覆盖率与训练流行度切片。
- 按用户整簇配对 bootstrap，比较固定模型的 RMSE 差。
- 12 项边界测试；仓库根目录 CI 在 Linux 与 Windows 运行这些测试。

![模型基线](reports/figures/model_comparison.svg)

## 文件导航

```text
MovieLensRatingLab/
  docs/LEARNING_GUIDE.md  # 完整教程，按顺序学习
  notebooks/             # 你执行代码、记录观察的工作区
  src/rating_lab/        # 数据、模型、bootstrap、CLI 与报告
  tests/test_core.py     # 时间边界、冷启动、重采样等测试
  reports/               # 初版聚合结果
  reports/learning/      # 按教程运行后生成的个人实验结果
  pyproject.toml         # 可编辑安装与固定直接依赖
```

Python 3.11+；首次运行从官方获取约 5 MB 原包并校验 SHA-256，不需要 API Key。安装和运行命令全部从教程第 0 步开始，不必先自行拼接环境步骤。

## 数据与解释范围

数据来源：[GroupLens 100K](https://grouplens.org/datasets/movielens/100k/)、[官方 README 与许可](https://files.grouplens.org/datasets/movielens/ml-100k-README.txt)。100,000 条评分、943 位用户、1,682 部电影，来自 1997–1998 年。这是固定历史教学基准，不能外推到今天所有观众。

评分预测误差不等于线上推荐质量。当前测试基线已公开，后续在同一尾段的比较属于探索；独立确认需要额外未参与选择的数据。

代码与原创文档使用 MIT 许可，MovieLens 数据适用单独条款。仓库不分发原包、行级评分、逐用户预测或训练参数；Notebook 提交前清空输出。完整数据背景和引用见教程末尾。
