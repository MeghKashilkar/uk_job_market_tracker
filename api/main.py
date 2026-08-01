"""FastAPI application backing the dashboard.

Every read endpoint takes the same optional filter parameters (``role_category``,
``seniority``, ``location``, ``region``, ``contract_type``), each repeatable, so
the frontend can apply one filter bar consistently across all views.

Run locally::

    uvicorn api.main:app --reload
"""


# NOTE: deliberately no `from __future__ import annotations` here. It turns the
# Annotated[...] parameter hints below into string ForwardRefs that pydantic
# cannot resolve for FastAPI's class-based dependencies, which fails at request
# time (only once a value is actually supplied). `X | None` needs no future
# import on the Python versions this targets.
import os
from collections import Counter
from typing import Annotated, Any

import numpy as np
import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from api import refresh as refresh_service
from api.schemas import PredictionRequest, PredictionResponse
from api.state import ROOT, get_dataset, get_salary_model
from src.analytics import (
    FILTERABLE_COLUMNS,
    apply_filters,
    filter_options,
    json_safe,
    overview,
    recent_postings,
    salary_by_top_skill,
    salary_distribution,
    salary_histogram,
)
from src.salary_model import get_feature_columns
from src.skill_extraction import skill_demand_table, skill_trend_table
from src.skills_taxonomy import (
    SKILLS_TAXONOMY,
    skill_count_column,
    skill_to_category_map,
    total_skill_count,
)

API_TITLE = "UK Data & Tech Job Market Tracker API"
API_VERSION = "1.0.0"
WEB_DIR = ROOT / "web"

MAX_TREND_SKILLS = 8
DEFAULT_SKILL_LIMIT = 20
# A residual standard error on the log scale gives an honest interval around a
# point estimate; derived from the winning model's held-out log MAE.
PREDICTION_INTERVAL_LOG_SPREAD = 0.35

app = FastAPI(
    title=API_TITLE,
    version=API_VERSION,
    description="Skill demand, salary trends, and salary prediction for UK data/tech roles.",
)

# The frontend is served from a different origin on Vercel; when it is proxied
# through Vercel rewrites this is unused, but it keeps a direct API call working.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o for o in os.environ.get("CORS_ORIGINS", "*").split(",") if o],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class Filters:
    """The repeatable filter query parameters shared by every read endpoint."""

    def __init__(
        self,
        role_category: Annotated[list[str] | None, Query()] = None,
        seniority: Annotated[list[str] | None, Query()] = None,
        location: Annotated[list[str] | None, Query()] = None,
        region: Annotated[list[str] | None, Query()] = None,
        contract_type: Annotated[list[str] | None, Query()] = None,
    ) -> None:
        self.selections: dict[str, list[str]] = {
            "role_category": role_category or [],
            "seniority": seniority or [],
            "location": location or [],
            "region": region or [],
            "contract_type": contract_type or [],
        }

    def apply(self) -> pd.DataFrame:
        """The dataset narrowed to the current selection."""
        return apply_filters(load_dataset(), self.selections)


def load_dataset() -> pd.DataFrame:
    """Cached dataset, surfaced as a 503 when the pipeline has not been run."""
    try:
        return get_dataset()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


FilterDep = Annotated[Filters, Depends(Filters)]


def ok(payload: dict[str, Any]) -> JSONResponse:
    """Serialize a payload, scrubbing non-finite floats that are invalid JSON."""
    return JSONResponse(content=json_safe(payload))


@app.get("/api/health", tags=["meta"])
def health() -> JSONResponse:
    """Liveness probe that also reports whether data and model are present."""
    try:
        rows = len(get_dataset())
        data_error = None
    except FileNotFoundError as exc:
        rows, data_error = 0, str(exc)

    return ok(
        {
            "status": "ok" if data_error is None else "degraded",
            "version": API_VERSION,
            "dataset_rows": rows,
            "model_loaded": get_salary_model() is not None,
            "detail": data_error,
        }
    )


@app.get("/api/meta", tags=["meta"])
def meta(filters: FilterDep) -> JSONResponse:
    """Filter options, taxonomy summary, and model card for the whole dataset."""
    df = load_dataset()
    model = get_salary_model()

    collected = df["collected_at"].dropna() if "collected_at" in df else pd.Series(dtype=object)
    return ok(
        {
            "filters": filter_options(df),
            "active_filters": {k: v for k, v in filters.selections.items() if v},
            "taxonomy": {
                "categories": list(SKILLS_TAXONOMY),
                "skills_by_category": {
                    category: list(skills) for category, skills in SKILLS_TAXONOMY.items()
                },
                "total_skills": total_skill_count(),
            },
            "refresh": {
                "available": refresh_service.is_available(),
                "cooldown_seconds": refresh_service.cooldown_seconds(),
            },
            "dataset": {
                "total_rows": len(df),
                "collected_from": (
                    collected.min().strftime("%Y-%m-%d") if not collected.empty else None
                ),
                "collected_to": (
                    collected.max().strftime("%Y-%m-%d") if not collected.empty else None
                ),
            },
            "model": (
                None
                if model is None
                else {
                    "name": model.name,
                    "n_training_rows": model.n_training_rows,
                    "mae_gbp": round(model.mae_gbp),
                    "r2": round(model.r2, 3),
                }
            ),
        }
    )


@app.get("/api/overview", tags=["dashboard"])
def get_overview(filters: FilterDep) -> JSONResponse:
    """Headline metrics and the market-shape charts."""
    return ok(overview(filters.apply()))


@app.get("/api/skills", tags=["dashboard"])
def get_skills(
    filters: FilterDep,
    category: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = DEFAULT_SKILL_LIMIT,
) -> JSONResponse:
    """Ranked skill demand, optionally narrowed to one taxonomy category."""
    demand = skill_demand_table(filters.apply()["skills"])
    if not demand.empty and category and category != "All":
        demand = demand[demand["category"] == category]

    return ok(
        {
            "categories": list(SKILLS_TAXONOMY),
            "total_distinct_skills": len(demand),
            "skills": demand.head(limit).to_dict(orient="records"),
        }
    )


@app.get("/api/skills/trend", tags=["dashboard"])
def get_skill_trend(
    filters: FilterDep,
    skills: Annotated[list[str] | None, Query()] = None,
    freq: Annotated[str, Query(pattern="^[WMD]$")] = "W",
) -> JSONResponse:
    """Mentions per period for up to eight named skills."""
    df = filters.apply()
    selected = (skills or [])[:MAX_TREND_SKILLS]
    if not selected:
        demand = skill_demand_table(df["skills"])
        selected = demand["skill"].head(4).tolist() if not demand.empty else []
    if not selected:
        return ok({"skills": selected, "series": []})

    trend = skill_trend_table(df, freq=freq)
    trend = trend[trend["skill"].isin(selected)]

    series: list[dict[str, Any]] = []
    for skill, group in trend.groupby("skill", observed=True):
        periods = pd.DatetimeIndex(group["period"])
        mentions = group["mentions"].to_numpy()
        series.append(
            {
                "skill": str(skill),
                "points": [
                    {"period": period.strftime("%Y-%m-%d"), "value": int(value)}
                    for period, value in zip(periods, mentions, strict=True)
                ],
            }
        )
    return ok({"skills": selected, "series": series})


@app.get("/api/salary", tags=["dashboard"])
def get_salary(filters: FilterDep) -> JSONResponse:
    """Salary distributions by role and seniority, plus the pay-by-skill view."""
    df = filters.apply()
    return ok(
        {
            "by_role": salary_distribution(df, "role_category"),
            "by_seniority": salary_distribution(df, "seniority"),
            "histogram": salary_histogram(df),
            "by_skill": salary_by_top_skill(df),
        }
    )


@app.get("/api/postings", tags=["dashboard"])
def get_postings(
    filters: FilterDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> JSONResponse:
    """Most recent postings matching the filters."""
    return ok({"postings": recent_postings(filters.apply(), limit=limit)})


@app.post("/api/predict", response_model=PredictionResponse, tags=["model"])
def predict_salary(request: PredictionRequest) -> PredictionResponse:
    """Estimate an annual salary for a hypothetical posting.

    Skill selections are mapped through the taxonomy into the per-category count
    features the model was trained on, so picking "Spark" and "Airflow" moves the
    data-engineering feature rather than a generic skill counter.
    """
    model = get_salary_model()
    if model is None:
        raise HTTPException(
            status_code=503,
            detail="No trained model available. Run: python -m src.train_salary_model",
        )

    category_of = skill_to_category_map()
    recognised = [skill for skill in request.skills if skill in category_of]
    ignored = [skill for skill in request.skills if skill not in category_of]

    row: dict[str, Any] = dict.fromkeys(get_feature_columns(), 0)
    row.update(
        {
            "role_category": request.role_category,
            "seniority": request.seniority,
            "region": request.region,
            "contract_type": request.contract_type,
            "contract_time": request.contract_time,
            "n_skills_total": len(recognised),
            "description_length": request.description_length,
        }
    )
    for category, count in Counter(category_of[skill] for skill in recognised).items():
        row[skill_count_column(category)] = count

    features = pd.DataFrame([row])[get_feature_columns()]
    predicted_log = float(model.estimator.predict(model.preprocessor.transform(features))[0])

    return PredictionResponse(
        predicted_salary=round(float(np.exp(predicted_log))),
        lower_bound=round(float(np.exp(predicted_log - PREDICTION_INTERVAL_LOG_SPREAD))),
        upper_bound=round(float(np.exp(predicted_log + PREDICTION_INTERVAL_LOG_SPREAD))),
        model_name=model.name,
        n_training_rows=model.n_training_rows,
        mae_gbp=round(model.mae_gbp),
        r2=round(model.r2, 3),
        skills_recognised=recognised,
        skills_ignored=ignored,
    )


@app.post("/api/refresh", tags=["data"], status_code=202)
def trigger_refresh() -> JSONResponse:
    """Start a background pull of the newest Adzuna postings.

    Returns immediately with 202; poll ``/api/refresh/status`` for progress.
    Disabled unless Adzuna credentials are configured, and rate-limited so a
    public button cannot burn the free-tier API quota.
    """
    if not refresh_service.is_available():
        raise HTTPException(
            status_code=503,
            detail=(
                "Live refresh is disabled: ADZUNA_APP_ID / ADZUNA_APP_KEY are not set "
                "on this server."
            ),
        )
    if refresh_service.is_running():
        raise HTTPException(status_code=409, detail="A refresh is already running.")

    remaining = refresh_service.cooldown_remaining()
    if remaining:
        raise HTTPException(
            status_code=429,
            detail=f"Refreshed recently - try again in {remaining}s.",
        )

    refresh_service.start_refresh()
    return ok(refresh_service.get_state())


@app.get("/api/refresh/status", tags=["data"])
def refresh_status() -> JSONResponse:
    """Progress of the most recent refresh."""
    return ok(refresh_service.get_state())


# Serving the built frontend from the API makes local development a single
# process; on Vercel the static files are served by the CDN and this is unused.
if WEB_DIR.is_dir():
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")


__all__ = ["FILTERABLE_COLUMNS", "app"]
