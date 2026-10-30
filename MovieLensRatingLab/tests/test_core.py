"""Protect the experiment's time boundary, fallback rules and sampling unit."""

import unittest

import numpy as np
import pandas as pd

from rating_lab.bootstrap import paired_user_bootstrap
from rating_lab.data import temporal_split
from rating_lab.models import BiasModel


def ratings_frame(timestamps):
    size = len(timestamps)
    return pd.DataFrame(
        {
            "row_id": np.arange(size),
            "user_id": np.arange(size) % 3 + 1,
            "movie_id": np.arange(size) % 4 + 10,
            "rating": np.arange(size) % 5 + 1,
            "timestamp": timestamps,
        }
    )


class TemporalSplitTests(unittest.TestCase):
    def test_unsorted_rows_are_partitioned_without_losing_observations(self):
        source = ratings_frame(np.repeat(np.arange(20), 3))
        source = source.sample(frac=1, random_state=7).reset_index(drop=True)
        original = source.copy(deep=True)

        train, validation, test = temporal_split(source)

        self.assertTrue(all(len(part) > 0 for part in (train, validation, test)))
        self.assertLess(train.timestamp.max(), validation.timestamp.min())
        self.assertLess(validation.timestamp.max(), test.timestamp.min())
        combined_ids = pd.concat([train, validation, test]).row_id
        self.assertEqual(len(combined_ids), len(source))
        self.assertEqual(combined_ids.nunique(), len(source))
        self.assertEqual(set(combined_ids), set(source.row_id))
        pd.testing.assert_frame_equal(source, original)

    def test_equal_timestamps_never_cross_a_boundary(self):
        source = ratings_frame([100] * 14 + [200] * 6 + [300] * 6 + [400] * 4)
        train, validation, test = temporal_split(
            source, train_fraction=0.5, validation_fraction=0.25
        )
        timestamp_sets = [set(part.timestamp) for part in (train, validation, test)]
        self.assertTrue(timestamp_sets[0].isdisjoint(timestamp_sets[1]))
        self.assertTrue(timestamp_sets[0].isdisjoint(timestamp_sets[2]))
        self.assertTrue(timestamp_sets[1].isdisjoint(timestamp_sets[2]))
        self.assertLess(train.timestamp.max(), validation.timestamp.min())
        self.assertLess(validation.timestamp.max(), test.timestamp.min())

    def test_too_few_distinct_times_cannot_form_three_periods(self):
        for timestamps in ([], [100], [100, 100, 200, 200]):
            with self.subTest(timestamps=timestamps):
                with self.assertRaises(ValueError):
                    temporal_split(ratings_frame(timestamps))


class BiasModelTests(unittest.TestCase):
    def setUp(self):
        self.train = pd.DataFrame(
            {
                "user_id": [1, 1, 2, 2],
                "movie_id": [10, 20, 10, 20],
                "rating": [5.0, 4.0, 2.0, 1.0],
                "timestamp": [1, 2, 3, 4],
            }
        )
        self.queries = pd.DataFrame(
            {"user_id": [99, 99, 1, 1], "movie_id": [99, 10, 99, 10]}
        )

    def test_global_model_predicts_training_mean_for_every_query(self):
        model = BiasModel(mode="global").fit(self.train)
        np.testing.assert_allclose(model.predict(self.queries), 3.0)

    def test_movie_model_uses_known_movie_and_falls_back_for_new_movie(self):
        model = BiasModel(mode="movie", strength=1.0).fit(self.train)
        predictions = model.predict(self.queries)
        self.assertAlmostEqual(float(predictions[0]), 3.0)
        self.assertGreater(predictions[1], 3.0)
        self.assertAlmostEqual(float(predictions[2]), 3.0)
        self.assertAlmostEqual(float(predictions[1]), float(predictions[3]))

    def test_user_movie_model_has_defined_cold_start_fallbacks(self):
        model = BiasModel(mode="user_movie", strength=1.0).fit(self.train)
        predictions = model.predict(self.queries)
        self.assertAlmostEqual(float(predictions[0]), 3.0)
        self.assertGreater(predictions[1], 3.0)
        self.assertGreater(predictions[2], 3.0)
        self.assertGreater(predictions[3], predictions[1])
        self.assertGreater(predictions[3], predictions[2])

    def test_predictions_do_not_read_held_out_ratings(self):
        model = BiasModel(mode="user_movie", strength=1.0).fit(self.train)
        low_labels = self.queries.assign(rating=1.0, timestamp=500)
        high_labels = self.queries.assign(rating=5.0, timestamp=900)
        np.testing.assert_array_equal(model.predict(low_labels), model.predict(high_labels))

    def test_fit_preserves_training_data_and_predictions_stay_on_rating_scale(self):
        original = self.train.copy(deep=True)
        for mode in ("global", "movie", "user_movie"):
            with self.subTest(mode=mode):
                predictions = BiasModel(mode=mode, strength=0.01).fit(self.train).predict(
                    self.queries
                )
                self.assertTrue(np.isfinite(predictions).all())
                self.assertTrue((predictions >= 1.0).all())
                self.assertTrue((predictions <= 5.0).all())
        pd.testing.assert_frame_equal(self.train, original)


class PairedUserBootstrapTests(unittest.TestCase):
    def test_identical_predictions_have_zero_difference_and_interval(self):
        truth = np.array([1.0, 3.0, 4.0, 5.0])
        predictions = np.array([2.0, 3.5, 3.5, 4.0])
        result = paired_user_bootstrap(
            truth, predictions, predictions, np.array([1, 1, 2, 2]), n_boot=100, seed=3
        )
        self.assertAlmostEqual(result["delta_rmse"], 0.0)
        np.testing.assert_allclose(result["ci95"], [0.0, 0.0])

    def test_better_candidate_has_negative_paired_error_difference(self):
        truth = np.array([2.0, 3.0, 4.0, 3.0])
        result = paired_user_bootstrap(
            truth, truth + 1.0, truth, np.array([1, 1, 2, 2]), n_boot=100, seed=3
        )
        self.assertAlmostEqual(result["delta_rmse"], -1.0)
        self.assertLess(result["ci95"][1], 0.0)

    def test_repeated_users_are_resampled_as_whole_clusters(self):
        # One prolific user improves, while one user with a single rating worsens.
        # Both all-user-1 and all-user-2 draws must remain possible. Sampling rows
        # independently would conceal much of the uncertainty in this example.
        truth = np.full(13, 3.0)
        reference = np.full(13, 4.0)
        candidate = np.array([3.0] * 12 + [5.0])
        users = np.array([1] * 12 + [2])
        result = paired_user_bootstrap(
            truth, reference, candidate, users, n_boot=500, seed=17
        )
        np.testing.assert_allclose(result["ci95"], [-1.0, 1.0])

    def test_seed_reproduces_interval_on_small_sample(self):
        truth = np.array([2.0, 4.0, 3.0, 5.0, 1.0, 2.0])
        reference = np.array([3.0, 3.0, 3.5, 4.0, 2.0, 2.0])
        candidate = np.array([2.0, 4.0, 3.0, 4.0, 3.0, 3.0])
        users = np.array([1, 1, 2, 2, 3, 3])
        first = paired_user_bootstrap(
            truth, reference, candidate, users, n_boot=200, seed=11
        )
        second = paired_user_bootstrap(
            truth, reference, candidate, users, n_boot=200, seed=11
        )
        self.assertAlmostEqual(first["delta_rmse"], second["delta_rmse"])
        np.testing.assert_array_equal(first["ci95"], second["ci95"])


if __name__ == "__main__":
    unittest.main()
