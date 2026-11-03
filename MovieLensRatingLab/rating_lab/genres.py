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