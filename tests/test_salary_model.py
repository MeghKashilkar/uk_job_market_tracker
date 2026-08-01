"""Tests for salary feature engineering and the plausibility filter."""

import pandas as pd

from src.salary_model import (
    MAX_PLAUSIBLE_SALARY,
    MIN_PLAUSIBLE_SALARY,
    NUMERIC_COLS,
    build_xy,
    filter_salaried_rows,
    get_feature_columns,
)


def _sample_df() -> pd.DataFrame:
    """Four rows: one usable, three that each fail a different filter rule."""
    rows = [
        {
            "role_category": "Data Analyst",
            "seniority": "Senior",
            "region": "London",
            "contract_type": "permanent",
            "contract_time": "full_time",
            "n_skills_total": 5,
            "description_length": 900,
            "salary_midpoint": 45000,  # keeper
        },
        {
            "role_category": "Data Engineer",
            "seniority": "Mid-level",
            "region": None,
            "contract_type": "permanent",
            "contract_time": "full_time",
            "n_skills_total": 7,
            "description_length": 1100,
            "salary_midpoint": None,  # no salary -> dropped
        },
        {
            "role_category": "Data Scientist",
            "seniority": "Junior / Entry-level",
            "region": "Scotland",
            "contract_type": "contract",
            "contract_time": "full_time",
            "n_skills_total": 4,
            "description_length": 700,
            "salary_midpoint": 5000,  # implausibly low -> dropped
        },
        {
            "role_category": "Data Manager / Lead",
            "seniority": "Head / Director",
            "region": "London",
            "contract_type": "permanent",
            "contract_time": "full_time",
            "n_skills_total": 3,
            "description_length": 500,
            "salary_midpoint": 900000,  # implausibly high -> dropped
        },
    ]
    for column in NUMERIC_COLS:
        for row in rows:
            row.setdefault(column, 0)
    return pd.DataFrame(rows)


def test_filter_salaried_rows_drops_missing_and_outlier_salaries():
    filtered = filter_salaried_rows(_sample_df())
    assert len(filtered) == 1
    assert filtered.iloc[0]["role_category"] == "Data Analyst"


def test_filter_salaried_rows_fills_missing_categoricals():
    filtered = filter_salaried_rows(_sample_df())
    assert filtered["region"].notna().all()


def test_plausible_salary_bounds_are_sane():
    assert 0 < MIN_PLAUSIBLE_SALARY < MAX_PLAUSIBLE_SALARY


def test_get_feature_columns_no_duplicates():
    columns = get_feature_columns()
    assert len(columns) == len(set(columns))


def test_build_xy_returns_log_scaled_target_as_a_series():
    features, target = build_xy(_sample_df())
    assert isinstance(target, pd.Series)
    assert list(features.columns) == get_feature_columns()
    # log(45_000) ~= 10.7, i.e. the target is on the log scale, not in pounds.
    assert 10 < float(target.iloc[0]) < 11


def test_build_xy_raises_when_the_target_column_is_missing():
    try:
        build_xy(pd.DataFrame({"role_category": ["Data Analyst"]}))
    except KeyError as exc:
        assert "salary_midpoint" in str(exc)
    else:  # pragma: no cover - guards against a silent regression
        raise AssertionError("expected a KeyError for the missing salary column")
