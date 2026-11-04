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

## 方法、结果与结论

| 使用的方法 | 实际结果 | 结论 |
|---|---|---|
| 关键字段、重复组合、取值范围及ID关联检查 | 评分缺失、重复组合、越界和孤儿电影关联均为0；保留100,000条评分、1,682个电影ID | 本次统计使用全部有效评分，目录按源电影ID计算 |
| 完整月分组，并将总量拆为评分人数×人均评分 | 1997-10到11月：评分量10,304→23,980，人数152→288，人均67.79→83.26 | 该段增长同时伴随参与人数和人均记录量上升 |
| 电影级计数、排序与累计份额 | 前169部占评分42.87%，前337部占64.72%；755部低样本影片占目录44.89%，仅占评分5.27% | 评分证据集中在头部，大量目录影片只有少量评分 |
| 多标签1/k分摊，并对照不同均分权重 | 212,595条展开行的总权重约为100,000；Drama份额24.61%，评分等权/电影等权均分为3.687/3.187 | 类型份额须处理标签重叠，类型均分须说明权重口径 |
| n≥30门槛与m=50收缩均分排序 | Schindler's List以298条评分、收缩分4.332位列第一 | 片单同时考虑均分和评分量，排名不只由原均分决定 |
| 固定门槛，比较m=20/50/100的Top20成员 | m=20与100共同17部，Jaccard为73.91% | 主要成员相同，部分候选随收缩强度改变 |

这些数值均来自 [evidence.json](outputs/evidence.json)。各方法的选择理由、计算过程和结果解释见 [分析报告](docs/ANALYSIS_REPORT.md)。

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

这是1997–1998年的筛选样本；评分时间是提交时间。评分数不是播放量，评分用户不是平台月活，类型分摊份额不是市场份额。候选名单来自历史评分和明确的排序规则，结论限于这份样本。

数据适用GroupLens单独条款，MIT代码许可不覆盖源数据。引用：Harper & Konstan (2015), *The MovieLens Datasets: History and Context*. [DOI](https://doi.org/10.1145/2827872)。
