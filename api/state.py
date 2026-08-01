"""Process-wide loading of the processed dataset and trained salary model.

Both are read from disk once and cached: the dataset is a few MB and the model
is immutable at runtime, so re-reading them per request would add latency
without ever changing the answer.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd

from src.process_data import DEFAULT_OUTPUT, load_processed

ROOT = Path(__file__).resolve().parents[1]
MODELS_DIR = ROOT / "models"
MODEL_PATH = MODELS_DIR / "salary_model.pkl"
PREPROCESSOR_PATH = MODELS_DIR / "salary_preprocessor.pkl"
METADATA_PATH = MODELS_DIR / "salary_model_metadata.json"


def dataset_path() -> Path:
    """Processed dataset location, overridable with ``JOBS_DATA_PATH``."""
    return Path(os.environ.get("JOBS_DATA_PATH", DEFAULT_OUTPUT))


@dataclass(frozen=True)
class SalaryModel:
    """A trained regressor plus the preprocessor and metrics that go with it."""

    estimator: Any
    preprocessor: Any
    name: str
    n_training_rows: int
    mae_gbp: float
    r2: float


@lru_cache(maxsize=1)
def get_dataset() -> pd.DataFrame:
    """Load the processed postings, with ``skills`` as real lists.

    Raises ``FileNotFoundError`` if the pipeline has not been run — the API
    turns that into a 503 rather than starting up in a broken state.
    """
    path = dataset_path()
    if not path.exists():
        raise FileNotFoundError(
            f"No processed dataset at {path}. Run:\n"
            "  python -m src.process_data --input data/raw/adzuna_jobs.csv"
        )

    df = load_processed(path)
    for column in ("collected_at", "created"):
        if column in df.columns:
            df[column] = pd.to_datetime(df[column], errors="coerce", utc=True)
    return df


@lru_cache(maxsize=1)
def get_salary_model() -> SalaryModel | None:
    """Load the trained model, or ``None`` if training has not been run yet."""
    if not (MODEL_PATH.exists() and PREPROCESSOR_PATH.exists()):
        return None

    import joblib

    metadata: dict[str, Any] = {}
    if METADATA_PATH.exists():
        metadata = json.loads(METADATA_PATH.read_text(encoding="utf-8"))
    metrics = metadata.get("metrics", {})

    return SalaryModel(
        estimator=joblib.load(MODEL_PATH),
        preprocessor=joblib.load(PREPROCESSOR_PATH),
        name=str(metadata.get("best_model_name", "unknown")),
        n_training_rows=int(metadata.get("n_training_rows", 0)),
        mae_gbp=float(metrics.get("mae_gbp", 0.0)),
        r2=float(metrics.get("r2", 0.0)),
    )


def reset_caches() -> None:
    """Drop cached state so the next request re-reads from disk (used by tests)."""
    get_dataset.cache_clear()
    get_salary_model.cache_clear()
