"""Tests for spaCy-backed skill extraction and the demand aggregation."""

import pandas as pd
import pytest

spacy = pytest.importorskip(
    "spacy",
    reason="spaCy + en_core_web_sm required for skill extraction tests",
)

from src.skill_extraction import extract_skills, skill_demand_table  # noqa: E402


def test_extract_skills_finds_expected_terms():
    text = "we need someone strong in python, sql and power bi with aws experience"
    skills = extract_skills(text)
    assert "Python" in skills
    assert "SQL" in skills
    assert "Power BI" in skills
    assert "AWS" in skills


def test_extract_skills_empty_text():
    assert extract_skills("") == []
    assert extract_skills(None) == []


def test_extract_skills_no_duplicates():
    text = "python python python sql sql"
    skills = extract_skills(text)
    assert skills.count("Python") == 1
    assert skills.count("SQL") == 1


def test_skill_demand_table_ranks_by_frequency():
    series = pd.Series([["Python", "SQL"], ["Python"], ["SQL", "AWS"]])
    table = skill_demand_table(series)
    top = table.iloc[0]
    assert top["skill"] in ("Python", "SQL")
    assert top["postings_mentioning"] == 2
    assert table["pct_of_postings"].max() == pytest.approx(200 / 3, abs=0.1)
