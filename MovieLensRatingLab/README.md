# MovieLens 数据分析：内容评分与候选片单

一个面向数据分析求职的纯 Python 案例：**用 pandas 从原始数据读取、清洗和指标计算，做到图表、结论与建议。**

## 学习入口

**[完整数据分析过程](docs/LEARNING_GUIDE.md)**

起点是你已下载的 `ml-100k.zip`。打开 [配套 Notebook](notebooks/01_explore.ipynb)，严格分两部分：**第一部分集中写完并保存 `rating_lab` 的全部7个文件；第二部分才统一导入，再读取、清洗和分析。** 两部分不穿插执行。

第一部分连续给出 `__init__.py`、`data_io.py`、`cleaning.py`、`monthly.py`、`concentration.py`、`genres.py`、`candidates.py` 的完整源码。全部保存好以后，才运行第二部分的第一个代码单元格。

教程围绕四个问题，逐一解释为什么用这种方法、怎样计算、实际结果是什么，以及能支持什么建议：

1. 月度评分参与怎样变化：完整月比较、人数与人均量分解。
2. 评分是否集中在少数影片：聚合、窗口排名与累计占比。
3. 多类型影片怎样分析：桥表关联、重复计算与 `1/k` 分摊。
4. 怎样形成口碑候选：样本门槛、收缩加权均分与敏感性检查。

主线不要求先训练预测模型。软件安装放在文末，仅在确实缺少依赖时参考。

## 数据与结果

- MovieLens 100K：100,000 条评分、943 位用户、1,682 部电影。
- 清洗保留全部有效评分；同名不同 ID 不盲删，缺失的非关键日期不补造。
- 类型连接展开为 212,595 行，按 `1/k` 分摊后还原为 100,000 条评分权重。
- 169 部评分最多的影片占评分 42.87%；小样本、年代和主动评分限制了外推。

这里的评分数不等于播放量，月评分用户不等于平台 MAU。案例模拟内容编辑分析任务，不是企业真实运营交付，也不声称带来业务增长。

[查看完整参考报告](reports/analyst/ANALYSIS_REPORT.md) · [质量审计](reports/analyst/audit.json) · [聚合指标](reports/analyst/metrics.json)

![评分集中度](reports/analyst/figures/rating_concentration.svg)

## 文件导航

```text
docs/LEARNING_GUIDE.md      # 唯一的主线教材：问题→方法→结果→建议
notebooks/01_explore.ipynb  # 个人执行代码和写观察的工作区
src/rating_lab/analyst.py  # 独立的自动复现实现，学习主线不依赖它
reports/analyst/           # 自动参考结果
notebooks/outputs/        # 按教程在学习目录中保存的聚合证据和图
notebooks/rating_lab/     # 第一部分由你集中写完全部7个文件
tests/                    # 数据关联、收缩与原有模型边界测试
```

学习主线只需要本地原包和 numpy/pandas/matplotlib，不联网、不自动下载、不依赖预生成数据，也不用先安装本项目包。先集中完成所有文件，再统一导入调用；完整源码全部在第一部分。自己的包放在 Notebook 学习文件夹中，和已有 `src/rating_lab` 分开。

已有自动参考实现仍可用 `python -m rating_lab.analyst` 复现报告，它属于单独的可选入口，不代替学习过程。

原有评分预测代码及其基线报告保留为可选技术扩展，不属于这次岗位案例的学习主线。

## 来源与许可

[GroupLens 官方来源](https://grouplens.org/datasets/movielens/100k/) · [原始字段说明与许可](https://files.grouplens.org/datasets/movielens/ml-100k-README.txt)

这是 1997–1998 年的筛选样本。代码和原创文档使用 MIT 许可，数据适用 GroupLens 单独条款。原包、数据库、行级评分和逐用户输出保留在本地，不提交 GitHub；Notebook 发布前清空输出。
