# file: rating_lab/monthly.py
"""按UTC评分月统计记录量、评分人数、人均量与日均量。"""

import pandas as pd


def make_monthly_table(ratings):
    if ratings.empty or not pd.api.types.is_datetime64_any_dtype(ratings["rated_at_utc"]):
        raise ValueError("请传入已转换rated_at_utc日期列的非空评分表")
    source = ratings.assign(
        rating_month=ratings["rated_at_utc"].dt.strftime("%Y-%m"),
        rating_day=ratings["rated_at_utc"].dt.normalize(),
    )
    result = source.groupby("rating_month", as_index=False).agg(
        rating_count=("rating", "size"), scoring_users=("user_id", "nunique"),
        rated_movies=("movie_id", "nunique"), rating_mean=("rating", "mean"),
        observed_day_count=("rating_day", "nunique"),
    )
    result["calendar_days"] = pd.to_datetime(result["rating_month"] + "-01").dt.days_in_month
    boundary_months = [source["rating_month"].min(), source["rating_month"].max()]
    result["is_partial_month"] = result["rating_month"].isin(boundary_months).astype(int)
    result["ratings_per_scoring_user"] = result["rating_count"] / result["scoring_users"]
    result["day_normalized_ratings"] = (result["rating_count"] / result["calendar_days"]).where(result["is_partial_month"].eq(0))
    return result[["rating_month", "rating_count", "scoring_users", "rated_movies", "rating_mean",
                   "calendar_days", "observed_day_count", "is_partial_month", "day_normalized_ratings",
                   "ratings_per_scoring_user"]].sort_values("rating_month").reset_index(drop=True)