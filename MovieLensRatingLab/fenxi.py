"""运行自己编写的 MovieLens 分析模块，保存聚合证据与两张图。"""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

import rating_lab
import rating_lab.data_io as data_module
import rating_lab.cleaning as cleaning_module
import rating_lab.monthly as monthly_module
import rating_lab.concentration as concentration_module
import rating_lab.genres as genres_module
import rating_lab.candidates as candidates_module


SOURCE_SHA256 = "50d2a982c66986937beb9ffb3aa76efe955bf3d5c6b761f4e3a7cd717c6a3229"
PROJECT_DIR = Path(__file__).resolve().parent


def _make_figures(monthly_table, movie_counts, output_dir, show_plots):
    """沿用原图的指标与布局；默认使用非交互后端并关闭已保存的图。"""
    import matplotlib

    if not show_plots:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    def save_svg(figure, name):
        destination = output_dir / name
        figure.tight_layout()
        with matplotlib.rc_context({"svg.fonttype": "none", "svg.hashsalt": "movielens-user-analysis-v1"}):
            figure.savefig(destination, metadata={"Date": None})
        destination.write_text(
            "\n".join(line.rstrip() for line in destination.read_text(encoding="utf-8").splitlines()) + "\n",
            encoding="utf-8", newline="\n",
        )
        if not show_plots:
            plt.close(figure)

    complete_months = monthly_table.loc[monthly_table["is_partial_month"].eq(0)]
    figure, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
    axes[0].plot(complete_months["rating_month"], complete_months["day_normalized_ratings"], marker="o")
    axes[0].set_ylabel("Ratings / calendar day")
    axes[1].plot(complete_months["rating_month"], complete_months["scoring_users"], marker="o")
    axes[1].set_ylabel("Distinct scoring users")
    save_svg(figure, "monthly_participation.svg")

    ordered = np.sort(movie_counts["rating_count"].to_numpy())
    x = np.r_[0, np.arange(1, len(ordered) + 1) / len(ordered)]
    y = np.r_[0, np.cumsum(ordered) / ordered.sum()]
    figure, axis = plt.subplots(figsize=(6, 5))
    axis.plot(x, y, label="Observed rating concentration")
    axis.plot([0, 1], [0, 1], "--", color="gray", label="Equal counts reference")
    axis.set(xlabel="Movie share (least rated first)", ylabel="Cumulative rating share")
    axis.legend()
    save_svg(figure, "concentration.svg")
    if show_plots:
        plt.show()


def run_analysis(zip_path, output_dir, show_plots=False):
    """复现四个分析问题，返回与桌面原结果同口径的聚合evidence。"""
    zip_path = Path(zip_path).expanduser().resolve()
    output_dir = Path(output_dir).expanduser().resolve()
    required_files = ["__init__.py", "data_io.py", "cleaning.py", "monthly.py",
                      "concentration.py", "genres.py", "candidates.py"]
    for filename in required_files:
        required = PROJECT_DIR / "rating_lab" / filename
        if not required.is_file():
            raise FileNotFoundError(f"缺少分析模块：{required}")
    if Path(rating_lab.__file__).resolve() != PROJECT_DIR / "rating_lab" / "__init__.py":
        raise ValueError("导入了其他同名rating_lab包，请使用本项目的Python环境")
    if not zip_path.is_file():
        raise FileNotFoundError(f"找不到原包：{zip_path}；请放入项目目录或通过--zip指定")
    if hashlib.sha256(zip_path.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise ValueError("请核对是否为官方MovieLens 100K固定原包")
    output_dir.mkdir(parents=True, exist_ok=True)

    ratings_raw, raw_movies, genres, users, flag_columns = data_module.read_source_tables(zip_path)
    print("评分原表：", ratings_raw.shape)
    print("电影原表：", raw_movies.shape)
    print("类型表：", genres.shape)
    ratings, movies, movie_genres, quality = cleaning_module.clean_tables(
        ratings_raw, raw_movies, genres, users, flag_columns,
    )
    print("\n数据质量检查：")
    print(pd.Series(quality).to_string())
    print("处理后：", ratings.shape, movies.shape, movie_genres.shape)

    monthly_table = monthly_module.make_monthly_table(ratings)
    assert monthly_table["rating_count"].sum() == len(ratings)
    assert np.allclose(monthly_table["rating_count"], monthly_table["scoring_users"] * monthly_table["ratings_per_scoring_user"])
    print("\n问题一：月度评分参与")
    print(monthly_table.to_string(index=False))

    movie_counts = concentration_module.make_movie_counts(ratings, movies)
    concentration = concentration_module.summarize_concentration(movie_counts)
    assert movie_counts["rating_count"].sum() == len(ratings)
    print("\n问题二：评分集中度")
    print(json.dumps(concentration, ensure_ascii=False, indent=2))

    genre_table, tagged_ratings = genres_module.make_genre_table(ratings, movie_genres)
    assert np.isclose(tagged_ratings["weight"].sum(), len(ratings))
    assert np.isclose(genre_table["weighted_share"].sum(), 1.0)
    print("\n问题三：类型覆盖与评分反馈")
    print("原评分行数：", len(ratings), "；类型展开行数：", len(tagged_ratings))
    print(genre_table.to_string(index=False))

    candidates = candidates_module.make_candidate_table(ratings, movies, min_ratings=30, prior_strength=50)
    first = candidates.iloc[0]
    expected_score = (first["rating_count"] * first["raw_mean"] + 50 * ratings["rating"].mean()) / (first["rating_count"] + 50)
    assert np.isclose(first["shrunk_mean"], expected_score)
    print("\n问题四：口碑候选前十名（n≥30，m=50）")
    print(candidates[["title", "rating_count", "raw_mean", "high_rating_ratio", "shrunk_mean", "shrunk_rank"]].head(10).to_string(index=False))
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
    print("\n收缩强度敏感性（Top20成员交集）：")
    print(pd.DataFrame(overlap_rows).to_string(index=False))

    evidence = {name: json.loads(frame.to_json(orient="records")) for name, frame in {
        "monthly": monthly_table, "genre": genre_table,
        "top30_candidates": candidates.head(30),
        "sensitivity": sensitivity_table[["prior_strength", "movie_id", "title", "rating_count", "raw_mean", "shrunk_mean", "shrunk_rank"]],
        "top20_overlap": pd.DataFrame(overlap_rows),
    }.items()}
    evidence["quality"] = quality
    evidence["concentration"] = concentration
    evidence["source_sha256"] = SOURCE_SHA256
    (output_dir / "evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _make_figures(monthly_table, movie_counts, output_dir, show_plots)
    print("\n聚合证据保存到：", output_dir / "evidence.json")
    return evidence


def main():
    parser = argparse.ArgumentParser(description="从本地MovieLens 100K原包复现四个Python分析问题")
    parser.add_argument("--zip", dest="zip_path", type=Path, default=PROJECT_DIR / "ml-100k.zip", help="本地固定原包路径")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_DIR / "outputs", help="聚合结果及图表目录")
    parser.add_argument("--show", dest="show_plots", action="store_true", help="保存后显示图形窗口")
    arguments = parser.parse_args()
    try:
        run_analysis(arguments.zip_path, arguments.output_dir, arguments.show_plots)
    except (FileNotFoundError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
