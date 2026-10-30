"""Paired user-cluster bootstrap, conditional on fitted models and time split."""

import numpy as np


def paired_user_bootstrap(y_true, reference_predictions, candidate_predictions,
                          user_ids, n_boot=1000, seed=42):
    """Negative delta_rmse favors the candidate. Resample entire users, paired.

    Each bootstrap score is rating-weighted over the resampled user clusters.
    This does not retrain models or measure uncertainty over future time periods.
    """
    y, reference, candidate = [np.asarray(x, dtype=float) for x in
                               [y_true, reference_predictions, candidate_predictions]]
    user_ids = np.asarray(user_ids)
    if y.ndim != 1 or len(y) == 0 or not (y.shape == reference.shape == candidate.shape == user_ids.shape):
        raise ValueError("Nonempty, equally sized one-dimensional inputs are required")
    if not all(np.isfinite(x).all() for x in [y, reference, candidate]) or n_boot < 1:
        raise ValueError("Finite inputs and at least one bootstrap sample are required")
    _, group = np.unique(user_ids, return_inverse=True)
    count = np.bincount(group)
    reference_sse = np.bincount(group, weights=(y - reference) ** 2)
    candidate_sse = np.bincount(group, weights=(y - candidate) ** 2)
    rng = np.random.default_rng(seed)
    deltas = np.empty(n_boot)
    for index in range(n_boot):
        sample = rng.integers(0, len(count), size=len(count))
        total = count[sample].sum()
        deltas[index] = np.sqrt(candidate_sse[sample].sum() / total) - np.sqrt(reference_sse[sample].sum() / total)
    delta = np.sqrt(np.mean((y - candidate) ** 2)) - np.sqrt(np.mean((y - reference) ** 2))
    return {"delta_rmse": float(delta), "ci95": np.quantile(deltas, [0.025, 0.975]).tolist(),
            "n_boot": int(n_boot), "n_users": int(len(count)), "seed": int(seed)}
