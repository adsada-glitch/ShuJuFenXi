# MovieLens 数据分析：内容评分与候选片单

使用 **Python + pandas**，从 MovieLens 100K 原始评分与电影目录出发，完成数据质量审计、月度参与分析、评分集中度、多标签分摊和口碑候选敏感性分析。

项目由 `fenxi.py` 调用自己建立的 `rating_lab` 模块，保留可复现代码、实际聚合结果和分析报告。

## 分析问题与方法

| 问题 | 方法 | 代码 |
|---|---|---|
| 评分参与随时间怎样变化？ | 完整月比较、评分人数与人均量分解、日历日标准化 | [monthly.py](rating_lab/monthly.py) |
| 评分是否集中在少数电影？ | 电影级聚合、稳定排序、累计份额和长尾切片 | [concentration.py](rating_lab/concentration.py) |
| 多类型电影怎样计算才不重复？ | 类型桥表、1/k分摊、三种均值口径 | [genres.py](rating_lab/genres.py) |
| 高分榜怎样考虑评分量？ | n≥30门槛、收缩均分、m=20/50/100敏感性 | [candidates.py](rating_lab/candidates.py) |

## 实际结果

- 检查并保留 **100,000 条评分、1,682 个电影ID**；评分缺失、重复组合、越界和孤儿关联均为0。
- 评分最多的前 **169 部**电影占评分 **42.87%**；前337部占64.72%。
- ≤20条评分的电影有 **755 部**，占目录44.89%，但只占评分5.27%。
- 类型连接展开为 **212,595 行**，1/k分摊后权重恢复为十万，避免把多标签记录误当新增评分。
- m=20与m=100时Top20共同成员为 **17 部**；结果描述参数选择的敏感性，不代表线上效果或统计显著性。

这些数值均可在 [evidence.json](outputs/evidence.json) 中核对。完整的问题、处理决策、结果解释和建议见 [分析报告](docs/ANALYSIS_REPORT.md)。

![月度评分参与](outputs/monthly_participation.svg)

![评分集中度](outputs/concentration.svg)

## 运行

将官方 `ml-100k.zip` 放在项目根目录，与 `fenxi.py` 同级，然后执行：

```bash
python -m pip install -r requirements.txt
python fenxi.py
```

数据也可以保存在其他位置：

```bash
python fenxi.py --zip "你的数据目录/ml-100k.zip" --output-dir "outputs"
```

默认保存图和聚合结果，不等待交互窗口；加 `--show` 可交互查看图。默认数据和结果路径基于脚本所在目录，支持从其他工作目录启动。

输出为 `evidence.json`、`monthly_participation.svg` 和 `concentration.svg`。自定义输出目录可用于独立复现，避免覆盖已有证据。

## 项目结构

```text
MovieLensRatingLab/
  fenxi.py
  rating_lab/
    __init__.py
    data_io.py
    cleaning.py
    monthly.py
    concentration.py
    genres.py
    candidates.py
  outputs/
    evidence.json
    monthly_participation.svg
    concentration.svg
  docs/ANALYSIS_REPORT.md
  tests/test_rating_lab.py
  requirements.txt
```

代码先集中在 `rating_lab` 中定义函数，再由 `fenxi.py` 统一导入和调用。源包和行级数据只在本地读取，不提交GitHub。测试命令：

```bash
python -m unittest discover -s tests -v
```

## 数据与范围

[GroupLens 官方来源](https://grouplens.org/datasets/movielens/100k/) · [字段与许可](https://files.grouplens.org/datasets/movielens/ml-100k-README.txt)

这是1997–1998年的筛选样本；评分时间是提交时间。评分数不是播放量，评分用户不是平台月活，类型分摊份额不是市场份额。候选名单只是供进一步复核的历史内容案例，不能证明收入、留存或推荐效果提升。

数据适用GroupLens单独条款，MIT代码许可不覆盖源数据。引用：Harper & Konstan (2015), *The MovieLens Datasets: History and Context*. [DOI](https://doi.org/10.1145/2827872)。
