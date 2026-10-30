"""Small, inspectable baselines: fixed global mean plus regularized biases."""

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class BiasModel:
    """Minimize squared error + strength * sum(bias**2), with fixed train mean.

    user_movie alternates exact user and movie coordinate updates. An unknown
    entity contributes zero bias, so predictions always have a defined fallback.
    """

    mode: str = "user_movie"
    strength: float = 10.0
    iterations: int = 20

    def fit(self, train):
        if self.mode not in {"global", "movie", "user_movie"}:
            raise ValueError("Unknown model mode")
        if not np.isfinite(self.strength) or self.strength < 0 or self.iterations < 1:
            raise ValueError("Invalid regularization or iteration count")
        ratings = train.rating.to_numpy(dtype=float)
        if len(ratings) == 0 or not np.isfinite(ratings).all() or not ((ratings >= 1) & (ratings <= 5)).all():
            raise ValueError("Training requires finite ratings in [1, 5]")
        self.mean_ = float(ratings.mean())
        self.user_bias_ = pd.Series(dtype=float)
        self.movie_bias_ = pd.Series(dtype=float)
        if self.mode == "global":
            return self
        users, user_ids = pd.factorize(train.user_id)
        movies, movie_ids = pd.factorize(train.movie_id)
        user_bias = np.zeros(len(user_ids))
        movie_bias = np.zeros(len(movie_ids))
        residual = ratings - self.mean_
        for _ in range(self.iterations):
            if self.mode == "user_movie":
                user_bias = np.bincount(users, weights=residual - movie_bias[movies]) / (
                    np.bincount(users) + self.strength
                )
            movie_bias = np.bincount(movies, weights=residual - user_bias[users]) / (
                np.bincount(movies) + self.strength
            )
        self.user_bias_ = pd.Series(user_bias, index=user_ids)
        self.movie_bias_ = pd.Series(movie_bias, index=movie_ids)
        return self

    def predict(self, frame):
        if not hasattr(self, "mean_"):
            raise ValueError("Fit the model before prediction")
        user_bias = frame.user_id.map(self.user_bias_).fillna(0).to_numpy(dtype=float)
        movie_bias = frame.movie_id.map(self.movie_bias_).fillna(0).to_numpy(dtype=float)
        return np.clip(self.mean_ + user_bias + movie_bias, 1.0, 5.0)
