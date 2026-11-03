# file: rating_lab/concentration.py
"""先按目录电影计数，再按稳定顺序汇总头部与长尾评分份额。"""

import numpy as np
import pandas as pd


def make_movie_counts(ratings, movies):
    if ratings.empty or movies.empty or movies["movie_id"].duplicated().any():
        raise ValueError("评分与目录不能为空，且目录电影ID须唯一")
    if not ratings["movie_id"].isin(movies["movie_id"]).all():
        raise ValueError("有评分找不到对应的目录电影")
    counts = ratings.groupby("movie_id", as_index=False).agg(rating_count=("rating", "size"))
    result = movies[["movie_id"]].merge(counts, on="movie_id", how="left", validate="one_to_one")
    result["rating_count"] = result["rating_count"].fillna(0).astype(int)
    result = result.sort_values(["rating_count", "movie_id"], ascending=[False, True]).reset_index(drop=True)
    result["count_rank"] = np.arange(1, len(result) + 1)
    result["cumulative_share"] = result["rating_count"].cumsum() / result["rating_count"].sum()
    return result


def summarize_concentration(movie_counts):
    if movie_counts.empty or movie_counts["rating_count"].sum() <= 0:
        raise ValueError("电影计数表不能为空，且总评分量须大于0")
    counts = movie_counts.sort_values(["rating_count", "movie_id"], ascending=[False, True])
    movie_count, rating_count = len(counts), int(counts["rating_count"].sum())
    top10_n, top20_n = int(np.ceil(movie_count * .10)), int(np.ceil(movie_count * .20))
    top10_ratings = int(counts.head(top10_n)["rating_count"].sum())
    top20_ratings = int(counts.head(top20_n)["rating_count"].sum())
    tail = counts.loc[counts["rating_count"].le(20)]
    tail_ratings = int(tail["rating_count"].sum())
    return {
        "movie_count": movie_count, "rating_count": rating_count,
        "top10_movie_count": top10_n, "top10_rating_count": top10_ratings,
        "top10_rating_share": top10_ratings / rating_count,
        "top20_movie_count": top20_n, "top20_rating_count": top20_ratings,
        "top20_rating_share": top20_ratings / rating_count,
        "longtail_movie_count": len(tail), "longtail_movie_share": len(tail) / movie_count,
        "longtail_rating_count": tail_ratings, "longtail_rating_share": tail_ratings / rating_count,
    }