"""Analyst invariants: keys, multi-label denominators and shrinkage behavior."""

import sqlite3
import unittest

import numpy as np
import pandas as pd

from rating_lab.analyst import _create_schema, load_queries, normalize_movies, shrink_mean


class MoviePreparationTests(unittest.TestCase):
    def test_same_title_keeps_distinct_movie_ids_and_unknown_flag(self):
        raw = pd.DataFrame({"movie_id": [1, 2], "title": ["Same title", "Same title"],
                            "release_date_raw": ["01-Jan-1990", ""],
                            "genre_0": [0, 1], "genre_1": [1, 0]})
        genres = pd.DataFrame({"genre_id": [0, 1], "genre": ["unknown", "Action"]})
        movies, membership, dates = normalize_movies(raw, genres, ["genre_0", "genre_1"])
        self.assertEqual(set(movies.movie_id), {1, 2})
        self.assertEqual(len(movies), 2)
        self.assertTrue(pd.isna(dates.iloc[1]))
        self.assertEqual(membership.loc[membership.movie_id.eq(2), "genre"].tolist(), ["unknown"])

    def test_shrinkage_is_stronger_for_small_samples_and_preserves_direction(self):
        values = shrink_mean(np.array([5.0, 5.0, 1.0]), np.array([5, 500, 5]), global_mean=3.0, prior_strength=50)
        self.assertTrue(3.0 < values[0] < values[1] < 5.0)
        self.assertTrue(1.0 < values[2] < 3.0)
        self.assertAlmostEqual(float(shrink_mean(3.0, 10, 3.0)), 3.0)


class AnalystSQLTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        _create_schema(self.connection)
        self.connection.executescript("""
            INSERT INTO users VALUES (1),(2);
            INSERT INTO genres VALUES (0,'unknown'),(1,'Action'),(2,'Comedy');
            INSERT INTO movies VALUES (1,'Same title','1990-01-01',1990),(2,'Same title',NULL,NULL);
            INSERT INTO movie_genres VALUES (1,1,'Action'),(1,2,'Comedy'),(2,0,'unknown');
            INSERT INTO ratings VALUES
                (1,1,5,1,'1997-09-20T00:00:00Z','1997-09'),
                (2,1,3,2,'1997-10-02T00:00:00Z','1997-10'),
                (1,2,1,3,'1997-10-03T00:00:00Z','1997-10'),
                (2,2,5,4,'1997-11-01T00:00:00Z','1997-11');
        """)

    def tearDown(self):
        self.connection.close()

    def test_genre_join_expands_counts_but_fractional_allocation_conserves_ratings(self):
        frame = pd.read_sql_query(load_queries()["genre"], self.connection)
        self.assertEqual(frame.rating_count.sum(), 6)
        self.assertGreater(frame.rating_count.sum(), 4)
        self.assertAlmostEqual(frame.weighted_count.sum(), 4.0)
        self.assertAlmostEqual(frame.weighted_share.sum(), 1.0)
        self.assertEqual(frame.set_index("genre").loc["unknown", "movie_count"], 1)

    def test_month_denominators_and_partial_boundaries_are_explicit(self):
        frame = pd.read_sql_query(load_queries()["monthly"], self.connection).set_index("rating_month")
        october = frame.loc["1997-10"]
        self.assertEqual(october.calendar_days, 31)
        self.assertEqual(october.observed_day_count, 2)
        self.assertAlmostEqual(october.ratings_per_scoring_user, 1.0)
        self.assertAlmostEqual(october.day_normalized_ratings, 2 / 31)
        self.assertEqual(frame.loc["1997-09", "is_partial_month"], 1)
        self.assertEqual(frame.loc["1997-11", "is_partial_month"], 1)
        self.assertTrue(pd.isna(frame.loc["1997-09", "day_normalized_ratings"]))

    def test_processed_database_enforces_movie_foreign_key(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute("INSERT INTO ratings VALUES (1,99,3,5,'1997-11-02T00:00:00Z','1997-11')")

    def test_candidate_sql_shrinks_small_sample_more_than_equal_mean_large_sample(self):
        self.connection.executemany("INSERT INTO users VALUES (?)", [(value,) for value in range(3, 333)])
        self.connection.executemany("INSERT INTO movies VALUES (?,?,NULL,NULL)", [(3, "Small sample"), (4, "Large sample")])
        self.connection.executemany(
            "INSERT INTO ratings VALUES (?,?,?,?,?,?)",
            [(user_id, 3 if user_id < 33 else 4, 5, 10, "1997-10-04T00:00:00Z", "1997-10")
             for user_id in range(3, 333)],
        )
        candidates = pd.read_sql_query(load_queries()["movie_candidates"], self.connection).set_index("movie_id")
        self.assertEqual(set(candidates.index), {3, 4})
        self.assertEqual(candidates.loc[3, "rating_count"], 30)
        self.assertEqual(candidates.loc[4, "rating_count"], 300)
        self.assertAlmostEqual(candidates.loc[3, "raw_mean"], candidates.loc[4, "raw_mean"])
        self.assertLess(candidates.loc[3, "shrunk_mean"], candidates.loc[4, "shrunk_mean"])
        self.assertLess(candidates.loc[4, "shrunk_mean"], 5.0)


if __name__ == "__main__":
    unittest.main()
