"""Rule-based classification of a job title into a role category and seniority.

Deliberately rule-based rather than ML: clean keyword rules cover the vast
majority of real-world title phrasing, a trained classifier would need labeled
data to beat this, and misclassifications here are easy to debug and extend
(append a keyword) instead of opaque.

Patterns are compiled once at import and combined per category, so classifying
a full dataset is a single pass of pre-built regexes rather than a re-parse per
row.
"""

from __future__ import annotations

import re

import pandas as pd

DEFAULT_ROLE = "Other"
DEFAULT_SENIORITY = "Mid-level"
UNSPECIFIED_SENIORITY = "Unspecified"

# Ordered so more specific categories are checked before generic ones
# (e.g. "Analytics Engineer" must not fall through to "Data Analyst").
ROLE_RULES: list[tuple[str, list[str]]] = [
    ("Machine Learning Engineer", [r"\bml engineer\b", r"machine learning engineer"]),
    ("Data Scientist", [r"data scientist"]),
    ("Analytics Engineer", [r"analytics engineer"]),
    ("Data Engineer", [r"data engineer"]),
    ("Data Architect", [r"data architect"]),
    ("BI Developer / Analyst", [r"\bbi\b", r"business intelligence"]),
    ("Data Analyst", [r"data analyst", r"\banalyst\b"]),
    ("Product Analyst", [r"product analyst"]),
    ("Data Manager / Lead", [r"head of data", r"data manager", r"analytics manager"]),
]

# "Mid-level" is the implicit fallback and therefore has no patterns.
SENIORITY_RULES: list[tuple[str, list[str]]] = [
    ("Head / Director", [r"\bhead of\b", r"\bdirector\b", r"\bvp\b", r"\bchief\b"]),
    ("Lead / Principal", [r"\blead\b", r"\bprincipal\b", r"\bstaff\b"]),
    ("Senior", [r"\bsenior\b", r"\bsr\.?\b"]),
    (
        "Junior / Entry-level",
        [r"\bjunior\b", r"\bjr\.?\b", r"\bgraduate\b", r"\bentry.level\b", r"\bintern\b"],
    ),
]


def _compile(rules: list[tuple[str, list[str]]]) -> list[tuple[str, re.Pattern[str]]]:
    """Combine each label's alternatives into one compiled, case-insensitive regex."""
    return [
        (label, re.compile("|".join(patterns), re.IGNORECASE))
        for label, patterns in rules
        if patterns
    ]


_ROLE_MATCHERS = _compile(ROLE_RULES)
_SENIORITY_MATCHERS = _compile(SENIORITY_RULES)


def classify_role(title: object) -> str:
    """Return the role category for a job title, or ``"Other"``."""
    if not isinstance(title, str) or not title.strip():
        return DEFAULT_ROLE
    for role, matcher in _ROLE_MATCHERS:
        if matcher.search(title):
            return role
    return DEFAULT_ROLE


def classify_seniority(title: object) -> str:
    """Return the seniority level for a job title, defaulting to ``"Mid-level"``."""
    if not isinstance(title, str) or not title.strip():
        return UNSPECIFIED_SENIORITY
    for level, matcher in _SENIORITY_MATCHERS:
        if matcher.search(title):
            return level
    return DEFAULT_SENIORITY


def add_classification_columns(df: pd.DataFrame, title_col: str = "title") -> pd.DataFrame:
    """Attach ``role_category`` and ``seniority`` columns derived from ``title_col``."""
    df = df.copy()
    titles = df[title_col]
    df["role_category"] = titles.map(classify_role)
    df["seniority"] = titles.map(classify_seniority)
    return df
