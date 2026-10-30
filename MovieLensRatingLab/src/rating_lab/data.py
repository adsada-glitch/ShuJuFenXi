"""Verified source acquisition and global temporal splitting."""

import hashlib
import io
import os
from pathlib import Path
import subprocess
import urllib.error
import urllib.request
import zipfile

import numpy as np
import pandas as pd

SOURCE_URL = "https://files.grouplens.org/datasets/movielens/ml-100k.zip"
SOURCE_SHA256 = "50d2a982c66986937beb9ffb3aa76efe955bf3d5c6b761f4e3a7cd717c6a3229"
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_ratings(data_dir=None):
    """Download once, check the fixed archive hash, then read ratings only.

    The Windows fallback uses the system certificate store; TLS verification is
    never disabled. No demographic data are needed by this project.
    """
    data_dir = Path(data_dir or PROJECT_ROOT / "data")
    data_dir.mkdir(parents=True, exist_ok=True)
    archive = data_dir / "ml-100k.zip"
    if not archive.exists():
        temporary = archive.with_suffix(".download")
        try:
            try:
                with urllib.request.urlopen(SOURCE_URL, timeout=60) as response:
                    temporary.write_bytes(response.read())
            except (urllib.error.URLError, OSError):
                if os.name != "nt":
                    raise
                destination = str(temporary.resolve()).replace("'", "''")
                command = (
                    "$ErrorActionPreference='Stop'; "
                    f"Invoke-WebRequest -Uri '{SOURCE_URL}' "
                    f"-OutFile '{destination}' -UseBasicParsing"
                )
                subprocess.run(
                    ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                    check=True, timeout=90, capture_output=True,
                )
            digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
            if digest != SOURCE_SHA256:
                raise ValueError("Source checksum mismatch; refusing to read data")
            temporary.replace(archive)
        finally:
            temporary.unlink(missing_ok=True)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise ValueError("Cached archive checksum mismatch; remove it and download again")
    with zipfile.ZipFile(archive) as source:
        ratings = pd.read_csv(
            io.BytesIO(source.read("ml-100k/u.data")), sep="\t",
            names=["user_id", "movie_id", "rating", "timestamp"],
        )
        (data_dir / "SOURCE_README.txt").write_bytes(source.read("ml-100k/README"))
    if len(ratings) != 100_000 or ratings.duplicated(["user_id", "movie_id"]).any():
        raise ValueError("Unexpected MovieLens 100K row count or duplicate user/movie pairs")
    if ratings.isna().any().any() or not ratings.rating.between(1, 5).all():
        raise ValueError("Invalid ratings")
    return ratings


def temporal_split(frame, train_fraction=0.70, validation_fraction=0.15):
    """Split by rating time. Ties belong entirely to the later partition.

    Percentages are approximate because equal timestamps cannot cross a boundary.
    The split uses timestamps only, never ratings or movie popularity.
    """
    if not 0 < train_fraction < 1 or not 0 < validation_fraction < 1:
        raise ValueError("Split fractions must be between zero and one")
    if train_fraction + validation_fraction >= 1:
        raise ValueError("A nonempty test fraction is required")
    if frame.empty or frame.timestamp.isna().any():
        raise ValueError("Nonempty, valid timestamps are required")
    ordered = frame.sort_values("timestamp", kind="stable").reset_index(drop=True)
    first = min(int(len(ordered) * train_fraction), len(ordered) - 1)
    second = min(int(len(ordered) * (train_fraction + validation_fraction)), len(ordered) - 1)
    first_time = ordered.timestamp.iloc[first]
    second_time = ordered.timestamp.iloc[second]
    train = ordered[ordered.timestamp < first_time].copy()
    validation = ordered[(ordered.timestamp >= first_time) & (ordered.timestamp < second_time)].copy()
    test = ordered[ordered.timestamp >= second_time].copy()
    if any(part.empty for part in [train, validation, test]):
        raise ValueError("Timestamp ties prevent three nonempty temporal partitions")
    return train, validation, test
