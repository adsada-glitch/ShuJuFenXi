"""Analyst invariants: keys, multi-label denominators and shrinkage behavior."""

import unittest

import numpy as np
import pandas as pd

from rating_lab.analyst import (
    analyze_candidates, analyze_genres, analyze_monthly,
    normalize_movies, shrink_mean, validate_relations,
)


class MoviePreparationTests(unittest.TestCase):
    def test_same_title_keeps_distinct_movie_ids_and_unknown_flag(self):
        raw = pd.DataFrame({"movie_id": [1, 2], "title": ["Same title", "Same title"],
                            "release_date_raw": ["01-Jan-1990", ""],
                            "genre_0": [0, 1], "genre_1": [1, 0]})
        genres = pd.DataFrame({"genre_id": [0, 1], "genre": ["unknown", "Action"]})
        movies, membership, dates = normalize_movies(raw, genres, ["genre_0", "genre_1"])
        self.assertEqual(set(movies.movie_id), {1, 2})
        self.assertEqual(len(movies), 2)
        self.assertTrue(pd.api.types.is_datetime64_any_dtype(movies.release_date))
        self.assertEqual(movies.release_date.dt.year.iloc[0], 1990)
        self.assertTrue(pd.isna(movies.release_date.iloc[1]))
        self.assertTrue(pd.isna(dates.iloc[1]))
        self.assertEqual(membership.loc[membership.movie_id.eq(2), "genre"].tolist(), ["unknown"])

    def test_shrinkage_is_stronger_for_small_samples_and_preserves_direction(self):
        values = shrink_mean(np.array([5.0, 5.0, 1.0]), np.array([5, 500, 5]), global_mean=3.0, prior_strength=50)
        self.assertTrue(3.0 < values[0] < values[1] < 5.0)
        self.assertTrue(1.0 < values[2] < 3.0)
        self.assertAlmostEqual(float(shrink_mean(3.0, 10, 3.0)), 3.0)


class AnalystDataFrameTests(unittest.TestCase):
    def setUp(self):
        dates = pd.to_datetime(["1997-09-20", "1997-10-02", "1997-10-03", "1997-11-01"], utc=True)
        self.ratings = pd.DataFrame({
            "user_id": [1, 2, 1, 2], "movie_id": [1, 1, 2, 2], "rating": [5, 3, 1, 5],
            "timestamp": dates.astype("int64") // 10**9,
        })
        self.movies = pd.DataFrame({"movie_id": [1, 2], "title": ["Same title", "Same title"]})
        self.membership = pd.DataFrame({
            "movie_id": [1, 1, 2], "genre_id": [1, 2, 0], "genre": ["Action", "Comedy", "unknown"],
        })

    def test_genre_join_expands_counts_but_fractional_allocation_conserves_ratings(self):
        frame = analyze_genres(self.ratings, self.membership)
        self.assertEqual(frame.rating_count.sum(), 6)
        self.assertGreater(frame.rating_count.sum(), 4)
        self.assertAlmostEqual(frame.weighted_count.sum(), 4.0)
        self.assertAlmostEqual(frame.weighted_share.sum(), 1.0)
        self.assertEqual(frame.set_index("genre").loc["unknown", "movie_count"], 1)
        # Equal-movie weighting must first aggregate each movie, not reuse an
        # average over the expanded rating rows when movie sample sizes differ.
        more_ratings = pd.concat([self.ratings, pd.DataFrame({
            "user_id": [3], "movie_id": [1], "rating": [5], "timestamp": [1],
        })], ignore_index=True)
        more_labels = pd.concat([self.membership, pd.DataFrame({
            "movie_id": [2], "genre_id": [1], "genre": ["Action"],
        })], ignore_index=True)
        action = analyze_genres(more_ratings, more_labels).set_index("genre").loc["Action"]
        self.assertAlmostEqual(action.rating_mean, 19 / 5)
        self.assertAlmostEqual(action.equal_movie_weight_mean, ((13 / 3) + 3) / 2)

    def test_month_denominators_and_partial_boundaries_are_explicit(self):
        frame = analyze_monthly(self.ratings).set_index("rating_month")
        october = frame.loc["1997-10"]
        self.assertEqual(october.calendar_days, 31)
        self.assertEqual(october.observed_day_count, 2)
        self.assertAlmostEqual(october.ratings_per_scoring_user, 1.0)
        self.assertAlmostEqual(october.day_normalized_ratings, 2 / 31)
        self.assertEqual(frame.loc["1997-09", "is_partial_month"], 1)
        self.assertEqual(frame.loc["1997-11", "is_partial_month"], 1)
        self.assertTrue(pd.isna(frame.loc["1997-09", "day_normalized_ratings"]))

    def test_invalid_dataframe_relations_fail_instead_of_silently_dropping_rows(self):
        validate_relations(self.ratings, self.movies, self.membership)
        for label, ratings, movies, membership in [
            ("orphan rating", self.ratings.assign(movie_id=[99, 1, 2, 2]), self.movies, self.membership),
            ("duplicate movie key", self.ratings, pd.concat([self.movies, self.movies.iloc[[0]]]), self.membership),
            ("duplicate label key", self.ratings, self.movies, pd.concat([self.membership, self.membership.iloc[[0]]])),
        ]:
            with self.subTest(problem=label):
                with self.assertRaises(ValueError):
                    validate_relations(ratings, movies, membership)

    def test_candidate_dataframe_shrinks_small_sample_more_than_equal_mean_large_sample(self):
        extra = pd.DataFrame({"user_id": np.arange(3, 333),
                              "movie_id": [3] * 30 + [4] * 300, "rating": 5, "timestamp": 10})
        ratings = pd.concat([self.ratings, extra], ignore_index=True)
        movies = pd.concat([self.movies, pd.DataFrame({"movie_id": [3, 4], "title": ["Small sample", "Large sample"]})], ignore_index=True)
        candidates = analyze_candidates(ratings, movies).set_index("movie_id")
        self.assertEqual(set(candidates.index), {3, 4})
        self.assertEqual(candidates.loc[3, "rating_count"], 30)
        self.assertEqual(candidates.loc[4, "rating_count"], 300)
        self.assertAlmostEqual(candidates.loc[3, "raw_mean"], candidates.loc[4, "raw_mean"])
        self.assertLess(candidates.loc[3, "shrunk_mean"], candidates.loc[4, "shrunk_mean"])
        self.assertLess(candidates.loc[4, "shrunk_mean"], 5.0)


if __name__ == "__main__":
    unittest.main()
