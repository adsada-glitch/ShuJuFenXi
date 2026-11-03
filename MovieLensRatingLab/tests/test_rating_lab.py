"""Small synthetic checks for the analysis contracts; no raw-data download."""

import unittest

import pandas as pd

from rating_lab.candidates import make_candidate_table
from rating_lab.cleaning import clean_tables
from rating_lab.concentration import make_movie_counts, summarize_concentration
from rating_lab.genres import make_genre_table
from rating_lab.monthly import make_monthly_table


def source_tables():
    dates = pd.to_datetime(
        ["1997-09-20", "1997-10-01", "1997-10-02", "1997-10-02", "1997-11-01"],
        utc=True,
    )
    ratings = pd.DataFrame({
        "user_id": [1, 2, 3, 4, 5], "movie_id": [10, 10, 10, 20, 30],
        "rating": [5, 1, 5, 1, 4], "timestamp": dates.astype("int64") // 10**9,
    })
    movies = pd.DataFrame({
        "movie_id": [10, 20, 30], "title": ["Same title", "Same title", "Other"],
        "release_date_raw": ["01-Jan-1990", "", "invalid-date"],
        "video_release_date_raw": ["", "", ""], "imdb_url": ["url", "", "url"],
        "genre_0": [0, 0, 1], "genre_1": [1, 1, 0], "genre_2": [1, 0, 0],
    })
    genres = pd.DataFrame({"genre_id": [0, 1, 2], "genre": ["unknown", "Action", "Comedy"]})
    users = pd.DataFrame({"user_id": [1, 2, 3, 4, 5]})
    return ratings, movies, genres, users, ["genre_0", "genre_1", "genre_2"]


class CleaningTests(unittest.TestCase):
    def test_valid_extremes_same_titles_unknown_and_dates_are_preserved(self):
        source = source_tables()
        originals = [frame.copy(deep=True) for frame in source[:4]]
        ratings, movies, memberships, quality = clean_tables(*source)

        self.assertEqual(ratings.rating.tolist(), [5, 1, 5, 1, 4])
        self.assertEqual(len(ratings), 5)
        self.assertEqual(movies.title.eq("Same title").sum(), 2)
        self.assertEqual(set(movies.movie_id), {10, 20, 30})
        self.assertEqual(str(ratings.rated_at_utc.dtype), "datetime64[ns, UTC]")
        self.assertTrue(pd.api.types.is_datetime64_any_dtype(movies.release_date))
        self.assertEqual(str(movies.release_year.dtype), "Int64")
        self.assertEqual(movies.release_date.isna().sum(), 2)
        self.assertEqual(quality["missing_release_dates"], 1)
        self.assertEqual(quality["invalid_dates"], 1)
        self.assertEqual(memberships.loc[memberships.movie_id.eq(30), "genre"].tolist(), ["unknown"])
        for original, unchanged in zip(originals, source[:4]):
            pd.testing.assert_frame_equal(original, unchanged)

    def test_orphan_and_duplicate_movie_ids_fail_before_joining(self):
        source = source_tables()
        orphan_ratings = source[0].copy()
        orphan_ratings.loc[0, "movie_id"] = 999
        duplicate_movies = pd.concat([source[1], source[1].iloc[[0]]], ignore_index=True)
        for name, ratings, movies in [
            ("orphan", orphan_ratings, source[1]),
            ("duplicate key", source[0], duplicate_movies),
        ]:
            with self.subTest(problem=name):
                with self.assertRaises(ValueError):
                    clean_tables(ratings, movies, *source[2:])

    def test_stars_outside_the_legal_range_are_rejected(self):
        for value in [0, 6]:
            with self.subTest(rating=value):
                source = source_tables()
                source[0].loc[0, "rating"] = value
                with self.assertRaises(ValueError):
                    clean_tables(*source)


class AggregationTests(unittest.TestCase):
    def test_multilabel_counts_expand_but_fractional_allocation_conserves_ratings(self):
        ratings, _, memberships, _ = clean_tables(*source_tables())
        table, tagged = make_genre_table(ratings, memberships)
        self.assertEqual(len(tagged), 8)
        self.assertGreater(table.rating_count.sum(), len(ratings))
        self.assertAlmostEqual(table.weighted_count.sum(), len(ratings))
        self.assertAlmostEqual(table.weighted_share.sum(), 1.0)
        action = table.set_index("genre").loc["Action"]
        self.assertAlmostEqual(action.rating_mean, 3.0)
        self.assertAlmostEqual(action.weighted_rating_mean, 2.6)
        self.assertAlmostEqual(action.equal_movie_weight_mean, 7 / 3)

    def test_monthly_denominator_uses_calendar_days_and_partial_boundary_months(self):
        ratings, _, _, _ = clean_tables(*source_tables())
        table = make_monthly_table(ratings).set_index("rating_month")
        october = table.loc["1997-10"]
        self.assertEqual(october.rating_count, 3)
        self.assertEqual(october.scoring_users, 3)
        self.assertEqual(october.observed_day_count, 2)
        self.assertEqual(october.calendar_days, 31)
        self.assertAlmostEqual(october.day_normalized_ratings, 3 / 31)
        self.assertAlmostEqual(october.ratings_per_scoring_user, 1.0)
        self.assertTrue(pd.isna(table.loc["1997-09", "day_normalized_ratings"]))
        self.assertTrue(pd.isna(table.loc["1997-11", "day_normalized_ratings"]))

    def test_catalog_zero_counts_and_ties_have_a_stable_movie_id_order(self):
        ratings = pd.DataFrame({"movie_id": [20, 10, 20, 10, 30], "rating": [3, 3, 3, 3, 3]})
        movies = pd.DataFrame({"movie_id": [40, 30, 20, 10]})
        counts = make_movie_counts(ratings, movies)
        self.assertEqual(counts.movie_id.tolist(), [10, 20, 30, 40])
        self.assertEqual(counts.rating_count.tolist(), [2, 2, 1, 0])
        self.assertAlmostEqual(counts.cumulative_share.iloc[-1], 1.0)
        summary = summarize_concentration(counts.sample(frac=1, random_state=7))
        self.assertEqual(summary["movie_count"], 4)
        self.assertEqual(summary["top10_movie_count"], 1)
        self.assertEqual(summary["top10_rating_count"], 2)
        self.assertAlmostEqual(summary["top10_rating_share"], .4)


class CandidateTests(unittest.TestCase):
    def test_equal_means_with_less_evidence_shrink_more_and_low_means_shrink_up(self):
        ratings = pd.DataFrame({
            "movie_id": [10] * 30 + [20] * 300 + [30] * 300,
            "rating": [5] * 330 + [1] * 300,
        })
        movies = pd.DataFrame({"movie_id": [10, 20, 30], "title": ["Small", "Large", "Low"]})
        table = make_candidate_table(ratings, movies).set_index("movie_id")
        average = ratings.rating.mean()
        self.assertAlmostEqual(table.loc[10, "raw_mean"], table.loc[20, "raw_mean"])
        self.assertTrue(average < table.loc[10, "shrunk_mean"] < table.loc[20, "shrunk_mean"] < 5)
        self.assertTrue(1 < table.loc[30, "shrunk_mean"] < average)
        self.assertEqual(table.loc[10, "high_rating_ratio"], 1.0)
        self.assertEqual(table.loc[30, "high_rating_ratio"], 0.0)
        self.assertNotIn(10, make_candidate_table(ratings, movies, min_ratings=31).movie_id.tolist())

    def test_invalid_threshold_and_negative_prior_fail_and_empty_selection_is_allowed(self):
        ratings, movies, _, _ = clean_tables(*source_tables())
        for options in [{"min_ratings": 0}, {"prior_strength": -1}]:
            with self.subTest(options=options):
                with self.assertRaises(ValueError):
                    make_candidate_table(ratings, movies, **options)
        self.assertTrue(make_candidate_table(ratings, movies, min_ratings=100).empty)


if __name__ == "__main__":
    unittest.main()
