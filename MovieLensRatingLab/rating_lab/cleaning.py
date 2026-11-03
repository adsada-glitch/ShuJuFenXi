# file: rating_lab/cleaning.py
"""检查质量、统一日期并建立类型桥表；不按标题或评分高低删行。"""

import numpy as np
import pandas as pd


def clean_tables(ratings_raw, raw_movies, genres, users, flag_columns):
    """显式接收原表，返回三张处理后表和质量记录，不修改输入。"""
    if ratings_raw.empty or raw_movies.empty:
        raise ValueError("评分与电影原表不能为空")
    #处理时间戳
    rating_time = pd.to_datetime(ratings_raw["timestamp"], unit="s", utc=True, errors="coerce")
    release_dates = pd.to_datetime(raw_movies["release_date_raw"], format="%d-%b-%Y", errors="coerce")
    release_present = raw_movies["release_date_raw"].ne("")
    #计算质量指标
    quality = {
        "rating_rows": len(ratings_raw),
        "missing_rating_cells": int(ratings_raw.isna().sum().sum()),
        "duplicate_user_movie_pairs": int(ratings_raw.duplicated(["user_id", "movie_id"]).sum()),
        "out_of_range_ratings": int((~ratings_raw["rating"].between(1, 5)).sum()),
        "duplicate_movie_ids": int(raw_movies["movie_id"].duplicated().sum()),
        "duplicate_title_groups": int((raw_movies["title"].value_counts() > 1).sum()),
        "missing_release_dates": int((~release_present).sum()),
        "missing_video_dates": int(raw_movies["video_release_date_raw"].eq("").sum()),
        "missing_urls": int(raw_movies["imdb_url"].eq("").sum()),
        "invalid_dates": int((release_present & release_dates.isna()).sum()),
        "invalid_timestamps": int(rating_time.isna().sum()),
        "duplicate_user_ids": int(users["user_id"].duplicated().sum()),
        "duplicate_genre_ids": int(genres["genre_id"].duplicated().sum()),
        "missing_dimension_key_cells": int(raw_movies["movie_id"].isna().sum()+ users["user_id"].isna().sum()+ genres["genre_id"].isna().sum()),
        "orphan_rating_user_rows": int((~ratings_raw["user_id"].isin(users["user_id"])).sum()),
        "orphan_rating_movie_rows": int((~ratings_raw["movie_id"].isin(raw_movies["movie_id"])).sum()),
        "invalid_genre_flag_cells": int((~raw_movies[flag_columns].isin([0, 1])).sum().sum()),
    }
    critical = ["missing_rating_cells", "duplicate_user_movie_pairs", "out_of_range_ratings",
                "duplicate_movie_ids", "invalid_timestamps", "duplicate_user_ids", "duplicate_genre_ids",
                "missing_dimension_key_cells", "orphan_rating_user_rows", "orphan_rating_movie_rows",
                "invalid_genre_flag_cells"]
    errors = {name: quality[name] for name in critical if quality[name]}
    if errors:
        raise ValueError(f"关键数据检查失败：{errors}")

    ratings = ratings_raw.copy()
    ratings["rated_at_utc"] = rating_time
    ratings["rating_month"] = rating_time.dt.strftime("%Y-%m")
    movies = raw_movies[["movie_id", "title"]].copy()
    movies["release_date"] = release_dates
    movies["release_year"] = release_dates.dt.year.astype("Int64")
    movie_genres = raw_movies[["movie_id"] + flag_columns].melt(
        id_vars="movie_id", var_name="genre_flag", value_name="present",
    )
    movie_genres = movie_genres.loc[movie_genres["present"].eq(1)].copy()
    movie_genres["genre_id"] = movie_genres["genre_flag"].str.removeprefix("genre_").astype(int)
    movie_genres = movie_genres[["movie_id", "genre_id"]].merge(
        genres, on="genre_id", how="left", validate="many_to_one",
    )
    quality["duplicate_movie_genre_pairs"] = int(movie_genres.duplicated(["movie_id", "genre_id"]).sum())
    quality["movies_without_genre"] = int((~movies["movie_id"].isin(movie_genres["movie_id"])).sum())
    if quality["duplicate_movie_genre_pairs"] or quality["movies_without_genre"] or movie_genres["genre"].isna().any():
        raise ValueError("电影类型组合必须唯一，每部电影须有可识别的真实类型标记")
    genre_sizes = movie_genres.groupby("movie_id").size()
    quality["multi_genre_movies"] = int(genre_sizes.gt(1).sum())
    quality["unknown_genre_movies"] = int(movie_genres.loc[movie_genres["genre"].eq("unknown"), "movie_id"].nunique())
    quality["movie_genre_rows"] = len(movie_genres)

    joined = ratings.merge(movies, on="movie_id", how="left", validate="many_to_one", indicator=True)
    quality["rating_movie_join_rows"] = len(joined)
    quality["unmatched_rating_movie_rows"] = int(joined["_merge"].ne("both").sum())
    tagged = ratings.merge(movie_genres, on="movie_id", how="left", validate="many_to_many")
    quality["rating_genre_join_rows"] = len(tagged)
    quality["genre_weighted_rating_total"] = float((1.0 / tagged["movie_id"].map(genre_sizes)).sum())
    if len(joined) != len(ratings) or quality["unmatched_rating_movie_rows"]:
        raise ValueError("评分与电影的多对一关联没有保留原始评分粒度")
    if not np.isclose(quality["genre_weighted_rating_total"], len(ratings), rtol=1e-12, atol=1e-9):
        raise ValueError("类型展开后的1/k分摊未保留总评分权重")
    quality["clean_rating_rows"] = len(ratings)
    quality["clean_movie_rows"] = len(movies)
    return ratings, movies, movie_genres, quality