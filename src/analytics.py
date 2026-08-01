"""Dataset aggregations shared by the API layer.

Kept out of the web layer so every number the dashboard shows is computed by
plain, unit-testable pandas rather than inside a request handler.
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from src.salary_model import MAX_PLAUSIBLE_SALARY, MIN_PLAUSIBLE_SALARY, TARGET_COL

FilterValues = dict[str, list[str]]

FILTERABLE_COLUMNS = ("role_category", "seniority", "location", "region", "contract_type")
SALARY_COL = TARGET_COL


def numeric_column(df: pd.DataFrame, column: str) -> pd.Series:
    """Coerce ``column`` to floats, returning an all-NaN series when it is absent.

    Callers can then treat a missing column and a column full of unparseable
    junk identically, which is what every aggregation here wants.
    """
    if column not in df.columns:
        return pd.Series(pd.NA, index=df.index, dtype="Float64")
    return pd.to_numeric(df[column], errors="coerce")


def plausible_salary(df: pd.DataFrame) -> pd.Series:
    """Advertised salaries inside the range the model considers real.

    Adzuna mixes day rates and the occasional £500k outlier into the annual
    salary field. Every salary view shares this filter so the charts, the
    headline median, and the model all describe the same population.
    """
    salary = numeric_column(df, SALARY_COL)
    return salary.where(salary.between(MIN_PLAUSIBLE_SALARY, MAX_PLAUSIBLE_SALARY))


def _clean_labels(series: pd.Series) -> list[str]:
    """Sorted unique non-null string labels from a column."""
    return sorted({str(value) for value in series.dropna().unique() if str(value).strip()})


def filter_options(df: pd.DataFrame) -> FilterValues:
    """Every selectable value per filterable column, for populating the UI."""
    return {
        column: _clean_labels(df[column]) for column in FILTERABLE_COLUMNS if column in df.columns
    }


def apply_filters(df: pd.DataFrame, selections: dict[str, list[str]]) -> pd.DataFrame:
    """Narrow the dataset by the selected values of each filterable column.

    An empty (or absent) selection for a column means "no constraint", which is
    what an untouched filter control sends.
    """
    mask = pd.Series(True, index=df.index)
    for column, values in selections.items():
        if values and column in df.columns:
            mask &= df[column].astype(str).isin(values)
    return df.loc[mask]


def _period_counts(dates: pd.Series, freq: str = "W") -> list[dict[str, Any]]:
    """Count rows per time bucket, as ``[{period, count}]`` sorted by period."""
    parsed = pd.to_datetime(dates, errors="coerce", utc=True).dropna()
    if parsed.empty:
        return []
    periods = parsed.dt.tz_localize(None).dt.to_period(freq).dt.start_time
    counts = periods.value_counts().sort_index()
    return [
        {"period": period.strftime("%Y-%m-%d"), "count": int(count)}
        for period, count in zip(pd.DatetimeIndex(counts.index), counts.to_numpy(), strict=True)
    ]


def _top_counts(series: pd.Series, limit: int | None = None) -> list[dict[str, Any]]:
    """Value counts as ``[{label, count}]``, most frequent first."""
    counts = series.dropna().astype(str).value_counts()
    if limit is not None:
        counts = counts.head(limit)
    return [{"label": str(label), "count": int(count)} for label, count in counts.items()]


def overview(df: pd.DataFrame, top_locations: int = 10) -> dict[str, Any]:
    """Headline metrics plus the three overview charts' data."""
    salary = plausible_salary(df)
    has_salary = salary.notna()
    median_salary = salary.median()

    return {
        "totals": {
            "postings": len(df),
            "companies": int(df["company"].nunique()) if "company" in df else 0,
            "locations": int(df["location"].nunique()) if "location" in df else 0,
            "salary_coverage": round(float(has_salary.mean()), 4) if len(df) else 0.0,
            "median_salary": None if pd.isna(median_salary) else round(float(median_salary)),
        },
        "postings_per_week": _period_counts(df["created"]) if "created" in df else [],
        "by_role": _top_counts(df["role_category"]) if "role_category" in df else [],
        "by_seniority": _top_counts(df["seniority"]) if "seniority" in df else [],
        "top_locations": (
            _top_counts(df["location"], limit=top_locations) if "location" in df else []
        ),
    }


def boxplot_stats(values: pd.Series) -> dict[str, float] | None:
    """Five-number summary plus Tukey whiskers for one group.

    Returned instead of the raw values so the browser receives a few numbers per
    group rather than every salary in the dataset.
    """
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    if numeric.empty:
        return None

    q1, median, q3 = (float(numeric.quantile(q)) for q in (0.25, 0.5, 0.75))
    iqr = q3 - q1
    within = numeric[(numeric >= q1 - 1.5 * iqr) & (numeric <= q3 + 1.5 * iqr)]
    fenced = within if not within.empty else numeric
    lower, upper = fenced.min(), fenced.max()

    return {
        "min": float(lower),
        "q1": q1,
        "median": median,
        "q3": q3,
        "max": float(upper),
        "count": int(numeric.size),
    }


def salary_distribution(df: pd.DataFrame, group_col: str) -> list[dict[str, Any]]:
    """Box-plot summaries of salary per group, richest median first."""
    if group_col not in df.columns or SALARY_COL not in df.columns:
        return []

    salaries = plausible_salary(df)
    groups: list[dict[str, Any]] = []
    for label, rows in salaries.groupby(df[group_col].astype(str), observed=True):
        stats = boxplot_stats(rows)
        if stats is not None:
            groups.append({"label": str(label), **stats})

    groups.sort(key=lambda group: group["median"], reverse=True)
    return groups


def salary_histogram(df: pd.DataFrame, bins: int = 24) -> list[dict[str, Any]]:
    """Salary distribution as histogram buckets for the overview chart.

    Restricted to the same plausible range the model trains on: Adzuna mixes in
    the odd day rate and £500k outlier, and a single one of those otherwise
    squashes every real bar into the leftmost bucket.
    """
    salary = plausible_salary(df).dropna().astype(float)
    if salary.empty:
        return []

    counts, edges = pd.cut(salary, bins=bins, retbins=True)
    tally = counts.value_counts().sort_index()
    return [
        {
            "lower": round(float(edges[index])),
            "upper": round(float(edges[index + 1])),
            "count": int(count),
        }
        for index, count in enumerate(tally.to_numpy())
    ]


def salary_by_top_skill(df: pd.DataFrame, limit: int = 12) -> list[dict[str, Any]]:
    """Median salary for each of the most-demanded skills.

    This is the "which skills actually pay" view — the join of the NLP output
    and the salary data that neither half shows on its own.
    """
    if "skills" not in df.columns or SALARY_COL not in df.columns:
        return []

    paired = pd.DataFrame({"skills": df["skills"], SALARY_COL: plausible_salary(df)})
    exploded = paired.explode("skills").dropna(subset=["skills", SALARY_COL])
    if exploded.empty:
        return []

    grouped = exploded.groupby("skills", observed=True)[SALARY_COL].agg(["median", "size"])
    grouped = grouped[grouped["size"] >= 5].nlargest(limit, "size")

    return [
        {
            "skill": str(skill),
            "median_salary": round(float(row["median"])),
            "postings": int(row["size"]),
        }
        for skill, row in grouped.sort_values("median", ascending=False).iterrows()
    ]


def recent_postings(df: pd.DataFrame, limit: int = 50) -> list[dict[str, Any]]:
    """Most recently created postings, for the browsable table."""
    if "created" not in df.columns:
        return []

    recent = df.assign(
        _created=pd.to_datetime(df["created"], errors="coerce", utc=True),
        _salary=plausible_salary(df),
    )
    recent = recent.dropna(subset=["_created"]).nlargest(limit, "_created")

    records: list[dict[str, Any]] = []
    for _index, row in recent.iterrows():
        salary = row["_salary"]
        records.append(
            {
                "title": str(row.get("title_clean") or row.get("title") or ""),
                "company": str(row.get("company") or ""),
                "location": str(row.get("location") or ""),
                "role_category": str(row.get("role_category") or ""),
                "seniority": str(row.get("seniority") or ""),
                "salary": None if pd.isna(salary) else round(float(salary)),
                "skills": list(row.get("skills") or [])[:8],
                "created": row["_created"].strftime("%Y-%m-%d"),
                "url": str(row.get("redirect_url") or ""),
            }
        )
    return records


def json_safe(value: Any) -> Any:
    """Recursively replace NaN/Inf with ``None`` so the payload is valid JSON."""
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value
