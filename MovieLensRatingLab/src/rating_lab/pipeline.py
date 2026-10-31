"""One reproducible run: validate, freeze, refit, evaluate and report aggregates."""

import json
import platform
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .bootstrap import paired_user_bootstrap
from .data import PROJECT_ROOT, SOURCE_SHA256, SOURCE_URL, load_ratings, temporal_split
from .models import BiasModel

GRID = [1.0, 5.0, 10.0, 25.0, 50.0]


def metrics(y_true, predictions):
    residual = np.asarray(y_true) - np.asarray(predictions)
    return {"rmse": float(np.sqrt(np.mean(residual**2))),
            "mae": float(np.mean(np.abs(residual)))}


def time_description(frame):
    return {"n_ratings": int(len(frame)), "n_users": int(frame.user_id.nunique()),
            "n_movies": int(frame.movie_id.nunique()),
            "start_utc": pd.to_datetime(frame.timestamp.min(), unit="s", utc=True).isoformat(),
            "end_utc": pd.to_datetime(frame.timestamp.max(), unit="s", utc=True).isoformat()}


def run(output_dir=None, data_dir=None, n_boot=2000, seed=42):
    output = Path(output_dir or PROJECT_ROOT / "reports")
    figures = output / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    ratings = load_ratings(data_dir)
    train, validation, test = temporal_split(ratings)
    trials = []
    selected = {}
    for mode in ["global", "movie", "user_movie"]:
        strengths = [0.0] if mode == "global" else GRID
        for strength in strengths:
            model = BiasModel(mode=mode, strength=strength).fit(train)
            score = metrics(validation.rating, model.predict(validation))
            trials.append({"mode": mode, "strength": strength, **score})
        winner = min([trial for trial in trials if trial["mode"] == mode], key=lambda trial: trial["rmse"])
        selected[mode] = winner["strength"]
    # The test labels have not been consulted. Hyperparameters are now frozen.
    final_train = pd.concat([train, validation], ignore_index=True)
    models = {mode: BiasModel(mode=mode, strength=strength).fit(final_train)
              for mode, strength in selected.items()}
    predictions = {mode: model.predict(test) for mode, model in models.items()}
    scores = {mode: metrics(test.rating, prediction) for mode, prediction in predictions.items()}
    comparison = paired_user_bootstrap(test.rating, predictions["movie"], predictions["user_movie"],
                                       test.user_id, n_boot=n_boot, seed=seed)
    user_known = test.user_id.isin(final_train.user_id)
    movie_known = test.movie_id.isin(final_train.movie_id)
    coverage = {"known_user_fraction": float(user_known.mean()),
                "known_movie_fraction": float(movie_known.mean()),
                "both_known_fraction": float((user_known & movie_known).mean()),
                "both_unknown_fraction": float((~user_known & ~movie_known).mean())}
    # All slice definitions use final training data, never test popularity.
    count = test.movie_id.map(final_train.movie_id.value_counts()).fillna(0).to_numpy()
    popularity = np.select([count == 0, count <= 20, count <= 100],
                           ["unseen", "tail (1-20)", "middle (21-100)"], default="head (>100)")
    slices = []
    for label in ["unseen", "tail (1-20)", "middle (21-100)", "head (>100)"]:
        mask = popularity == label
        if not mask.any():
            continue
        slices.append({"slice_type": "movie_popularity", "slice": label,
                       "n_ratings": int(mask.sum()), "n_users": int(test.loc[mask, "user_id"].nunique()),
                       "scores": {mode: metrics(test.rating.to_numpy()[mask], pred[mask])
                                  for mode, pred in predictions.items()}})
    for label, mask in [("known_user", user_known.to_numpy()), ("unseen_user", ~user_known.to_numpy())]:
        if mask.any():
            slices.append({"slice_type": "user_coverage", "slice": label,
                           "n_ratings": int(mask.sum()), "n_users": int(test.loc[mask, "user_id"].nunique()),
                           "scores": {mode: metrics(test.rating.to_numpy()[mask], pred[mask])
                                      for mode, pred in predictions.items()}})
    result = {"dataset": "MovieLens 100K", "source_url": SOURCE_URL, "source_sha256": SOURCE_SHA256,
              "seed": seed, "split_policy": "global rating time 70/15/15; timestamp ties stay together",
              "partitions": {name: time_description(part) for name, part in
                             [("train", train), ("validation", validation), ("test", test)]},
              "validation_trials": trials, "selected_strength": selected,
              "final_training": "train + validation after freezing hyperparameters",
              "test_scores": scores, "test_coverage": coverage,
              "paired_comparison": {"reference": "movie", "candidate": "user_movie", **comparison},
              "slices": slices,
              "environment": {"python": platform.python_version(), "numpy": np.__version__,
                              "pandas": pd.__version__, "matplotlib": matplotlib.__version__}}
    (output / "metrics.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    make_figures(ratings, trials, scores, slices, figures)
    write_report(result, output)
    print(f"Report: {output / 'BASELINE_REPORT.md'}")
    for mode, score in scores.items():
        print(f"{mode:12} RMSE={score['rmse']:.4f} MAE={score['mae']:.4f}")
    print(f"Paired delta RMSE: {comparison['delta_rmse']:.4f}; 95% CI {comparison['ci95']}")
    return result


def make_figures(ratings, trials, scores, slices, figures):
    plt.rcParams.update({"figure.dpi": 140, "axes.spines.top": False, "axes.spines.right": False,
                         "svg.hashsalt": "rating-lab-v1", "svg.fonttype": "none", "font.size": 10})

    def save(fig, name):
        fig.tight_layout()
        fig.savefig(figures / f"{name}.svg", metadata={"Date": None})
        svg = figures / f"{name}.svg"
        svg.write_text("\n".join(line.rstrip() for line in svg.read_text(encoding="utf-8").splitlines()) + "\n", encoding="utf-8")
        fig.savefig(figures / f"{name}.png")
        plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(10, 3.7))
    counts = ratings.groupby(pd.to_datetime(ratings.timestamp, unit="s", utc=True).dt.strftime("%Y-%m")).size()
    axes[0].bar(counts.index, counts, color="#2A6F97")
    axes[0].tick_params(axis="x", rotation=45)
    axes[0].set(title="Observed ratings by month (descriptive)", ylabel="Ratings")
    axes[1].bar(["1", "2", "3", "4", "5"], ratings.rating.value_counts().sort_index(), color="#6B9080")
    axes[1].set(title="Observed rating distribution", xlabel="Stars", ylabel="Ratings")
    save(fig, "data_overview")
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.7))
    for mode, color in [("movie", "#2A6F97"), ("user_movie", "#D67A35")]:
        rows = [trial for trial in trials if trial["mode"] == mode]
        axes[0].plot([row["strength"] for row in rows], [row["rmse"] for row in rows], marker="o", label=mode, color=color)
    axes[0].set(xscale="log", xlabel="Regularization strength", ylabel="Validation RMSE", title="Tune on validation only")
    axes[0].legend()
    axes[1].bar(list(scores), [score["rmse"] for score in scores.values()], color=["#9EADBA", "#2A6F97", "#D67A35"])
    axes[1].set(ylabel="Test RMSE (lower is better)", title="Frozen baselines on future ratings", ylim=(0, 1.4))
    for i, score in enumerate(scores.values()):
        axes[1].text(i, score["rmse"] + .02, f"{score['rmse']:.3f}", ha="center")
    save(fig, "model_comparison")
    fig, axis = plt.subplots(figsize=(8, 4))
    rows = [row for row in slices if row["slice_type"] == "movie_popularity"]
    x = np.arange(len(rows))
    for offset, mode, color in [(-.18, "movie", "#2A6F97"), (.18, "user_movie", "#D67A35")]:
        axis.bar(x + offset, [row["scores"][mode]["rmse"] for row in rows], width=.35, label=mode, color=color)
    axis.set(xticks=x, xticklabels=[f"{row['slice']}\nn={row['n_ratings']}" for row in rows],
             ylabel="Test RMSE", title="Movie popularity defined from final training data")
    axis.legend()
    save(fig, "popularity_slices")


def write_report(result, output):
    scores, comparison = result["test_scores"], result["paired_comparison"]
    ci_low, ci_high = comparison["ci95"]
    interpretation = ("区间整体低于 0，此次测试中加入用户偏置的模型误差较低。" if ci_high < 0 else
                      "区间整体高于 0，此次测试中加入用户偏置的模型误差较高。" if ci_low > 0 else
                      "区间跨过 0，此次比较无法清楚区分两个模型的误差。")
    lines = ["# 初版基线报告", "", "本报告由 `python -m rating_lab run` 生成；这是待你解释和改进的起点。", "",
             "## 问题与实验协议", "", "用户和电影偏置能否改善未来记录评分的预测误差？", "",
             "使用固定 MovieLens 100K；按全局评分时间近似 70%/15%/15% 切分，同时间戳不跨集合。"
             "各基线在验证集选择正则化后，用训练+验证集重拟合，再统一评估测试集。", "",
             "| 集合 | 评分数 | 用户数 | 开始 UTC | 结束 UTC |", "|---|---:|---:|---|---|"]
    for name, part in result["partitions"].items():
        lines.append(f"| {name} | {part['n_ratings']} | {part['n_users']} | {part['start_utc']} | {part['end_utc']} |")
    lines += ["", "## 冻结后的基线", "", "| 模型 | 正则化 | Test RMSE ↓ | Test MAE ↓ |", "|---|---:|---:|---:|"]
    for mode, score in scores.items():
        lines.append(f"| {mode} | {result['selected_strength'][mode]:g} | {score['rmse']:.4f} | {score['mae']:.4f} |")
    lines += ["", "![基线比较](figures/model_comparison.svg)", "", "## 不确定性与覆盖率", "",
              f"预设比较为 `user_movie − movie`。按测试用户整簇、成对重采样 {comparison['n_boot']} 次，"
              f"RMSE 差为 **{comparison['delta_rmse']:.4f}**，95% 百分位区间 **[{ci_low:.4f}, {ci_high:.4f}]**。"
              f"{interpretation} 区间条件于当前已训练模型、测试用户群和时间窗口；没有包含重训或时间漂移的不确定性。", ""]
    for name, value in result["test_coverage"].items():
        lines.append(f"- {name}: {value:.1%}")
    lines += ["", "## 分组误差", "", "| 分组 | 评分数 | 用户数 | movie RMSE | user_movie RMSE |", "|---|---:|---:|---:|---:|"]
    for row in result["slices"]:
        lines.append(f"| {row['slice']} | {row['n_ratings']} | {row['n_users']} | {row['scores']['movie']['rmse']:.4f} | {row['scores']['user_movie']['rmse']:.4f} |")
    lines += ["", "![训练流行度分组](figures/popularity_slices.svg)", "", "## 解释边界", "",
              "- 仅衡量被主动记录的评分；没有曝光、点击或未喜欢的完整记录，不能当作线上推荐效果。",
              "- 1997–1998 年的历史样本且用户至少有 20 条评分；不能外推到今天所有观众或新用户。",
              "- 时间戳是评分提交时间；不等于观影或影片发行时间。",
              "- 分组误差是描述性诊断，没有分组显著性或因果结论；小分组尤其不稳定。",
              "- 初版已展示测试集结果。改进实验应另定更晚时间窗/滚动验证，不能反复看本测试集调参后再宣称独立确认。", "",
              "## 继续学习", "",
              "岗位案例主线请阅读 [完整数据分析过程](../docs/LEARNING_GUIDE.md)：从来源、清洗和SQL指标到结论建议。本报告是评分预测的可选技术扩展。", "",
              "![数据概览](figures/data_overview.svg)", "", "完整聚合指标和运行环境见 [metrics.json](metrics.json)。", ""]
    (output / "BASELINE_REPORT.md").write_text("\n".join(lines), encoding="utf-8")
