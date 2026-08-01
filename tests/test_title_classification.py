"""Tests for rule-based role and seniority classification."""

import pandas as pd

from src.title_classification import add_classification_columns, classify_role, classify_seniority


def test_classify_role_data_analyst():
    assert classify_role("Senior Data Analyst") == "Data Analyst"


def test_classify_role_prefers_specific_over_generic():
    # "Analytics Engineer" contains neither "data analyst" nor "data engineer"
    # verbatim, but should not fall through to the generic "\banalyst\b" rule.
    assert classify_role("Analytics Engineer") == "Analytics Engineer"


def test_classify_role_ml_engineer():
    assert classify_role("Lead Machine Learning Engineer") == "Machine Learning Engineer"


def test_classify_role_unknown_falls_back_to_other():
    assert classify_role("Warehouse Operative") == "Other"


def test_classify_role_handles_missing_title():
    assert classify_role(None) == "Other"
    assert classify_role("") == "Other"


def test_classify_seniority_head_of_data_is_not_junior():
    assert classify_seniority("Head of Data") == "Head / Director"


def test_classify_seniority_defaults_to_mid_level():
    assert classify_seniority("Data Engineer") == "Mid-level"


def test_classify_seniority_junior_variants():
    assert classify_seniority("Junior Data Analyst") == "Junior / Entry-level"
    assert classify_seniority("Data Analyst - Graduate Scheme") == "Junior / Entry-level"


def test_add_classification_columns():
    df = pd.DataFrame({"title": ["Senior Data Scientist", "Head of Data", "Warehouse Operative"]})
    result = add_classification_columns(df)
    assert list(result["role_category"]) == ["Data Scientist", "Data Manager / Lead", "Other"]
    assert list(result["seniority"]) == ["Senior", "Head / Director", "Mid-level"]
