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