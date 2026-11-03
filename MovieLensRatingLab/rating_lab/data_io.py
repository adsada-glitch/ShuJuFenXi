# file: rating_lab/data_io.py
"""从本地固定原包读取四张原始表，不下载或修改源数据。"""

import hashlib
import io
from pathlib import Path
import zipfile

import pandas as pd


def read_source_tables(zip_path):
    """返回评分、电影、类型、用户ID原表，以及类型标记列名。"""
    zip_path = Path(zip_path)
    expected_hash = "50d2a982c66986937beb9ffb3aa76efe955bf3d5c6b761f4e3a7cd717c6a3229"
    if hashlib.sha256(zip_path.read_bytes()).hexdigest() != expected_hash:
        raise ValueError("原包校验和不符，请核对来源和版本")
    with zipfile.ZipFile(zip_path) as source:
        ratings_raw = pd.read_csv(
            io.BytesIO(source.read("ml-100k/u.data")), sep="\t",
            names=["user_id", "movie_id", "rating", "timestamp"],
        )
        genres = pd.read_csv(
            io.BytesIO(source.read("ml-100k/u.genre")), sep="|",
            names=["genre", "genre_id"], encoding="latin-1",
        )
        flag_columns = [f"genre_{value}" for value in genres.sort_values("genre_id")["genre_id"]]
        raw_movies = pd.read_csv(
            io.BytesIO(source.read("ml-100k/u.item")), sep="|", encoding="latin-1",
            names=["movie_id", "title", "release_date_raw", "video_release_date_raw", "imdb_url"] + flag_columns,
            keep_default_na=False,
        )
        users = pd.read_csv(
            io.BytesIO(source.read("ml-100k/u.user")), sep="|", header=None,
            usecols=[0], encoding="latin-1",
        ).rename(columns={0: "user_id"})
    return ratings_raw, raw_movies, genres, users, flag_columns