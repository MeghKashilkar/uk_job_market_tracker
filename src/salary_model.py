"""Feature engineering and preprocessing for salary prediction.

Builds a feature matrix from role/seniority/location/contract metadata plus the
skill-category counts already computed during processing — deliberately not raw
text, so the salary model stays fast, interpretable, and independent of
whichever NLP library extracted the skills.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from src.skills_taxonomy import skill_count_columns

RANDOM_STATE = 42
TEST_SIZE = 0.2

CATEGORICAL_COLS = ["role_category", "seniority", "region", "contract_type", "contract_time"]
NUMERIC_COLS = ["n_skills_total", "description_length", *skill_count_columns()]

TARGET_COL = "salary_midpoint"
UNKNOWN_CATEGORY = "Unknown"

# Adzuna occasionally reports day rates or stipends in the annual salary field;
# these bounds drop those without hand-labeling each one.
MIN_PLAUSIBLE_SALARY = 15_000
MAX_PLAUSIBLE_SALARY = 250_000


def get_feature_columns() -> list[str]:
    """Feature columns, in the exact order the preprocessor expects."""
    return [*CATEGORICAL_COLS, *NUMERIC_COLS]


def filter_salaried_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Keep rows with a plausible annual salary, with features filled in.

    Adzuna only reports salary on a subset of postings, and a handful of
    outliers (day rates mislabeled as annual, etc.) slip through.
    """
    if TARGET_COL not in df.columns:
        raise KeyError(
            f"'{TARGET_COL}' column missing — run src.process_data on the raw postings first."
        )

    salary = pd.to_numeric(df[TARGET_COL], errors="coerce")
    in_range = salary.between(MIN_PLAUSIBLE_SALARY, MAX_PLAUSIBLE_SALARY)

    clean = df.loc[in_range].copy()
    clean[TARGET_COL] = salary.loc[in_range]
    for column in CATEGORICAL_COLS:
        source = clean[column] if column in clean else pd.Series(index=clean.index, dtype=object)
        clean[column] = source.fillna(UNKNOWN_CATEGORY).astype(str)
    for column in NUMERIC_COLS:
        source = clean[column] if column in clean else pd.Series(index=clean.index, dtype=float)
        clean[column] = pd.to_numeric(source, errors="coerce").fillna(0)
    return clean.reset_index(drop=True)


def build_preprocessor() -> ColumnTransformer:
    """One-hot encode the categoricals and standardize the numeric features."""
    return ColumnTransformer(
        transformers=[
            (
                "cat",
                Pipeline([("onehot", OneHotEncoder(handle_unknown="ignore"))]),
                CATEGORICAL_COLS,
            ),
            ("num", Pipeline([("scale", StandardScaler())]), NUMERIC_COLS),
        ]
    )


def build_xy(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """Return ``(X, y)`` where ``y`` is ``log(salary_midpoint)``.

    UK data-role salaries are right-skewed (a few Head-of-Data postings pull the
    mean well above the median); training on the log scale stops those outliers
    from dominating the loss. Predictions are exponentiated back to £ for
    reporting.
    """
    clean = filter_salaried_rows(df)
    features = clean[get_feature_columns()]
    target = pd.Series(
        np.log(clean[TARGET_COL].to_numpy(dtype=float)),
        index=clean.index,
        name="log_salary",
    )
    return features, target


def split_data(
    features: pd.DataFrame,
    target: pd.Series,
    test_size: float = TEST_SIZE,
    random_state: int = RANDOM_STATE,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series]:
    """Deterministic train/test split shared by training and evaluation."""
    return train_test_split(features, target, test_size=test_size, random_state=random_state)
