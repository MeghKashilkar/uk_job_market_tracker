"""Request/response models for the API.

Only the request bodies are modelled strictly — responses are plain aggregation
dictionaries built by :mod:`src.analytics`, and re-declaring each chart's shape
here would be duplicated surface with nothing to enforce.
"""


# No `from __future__ import annotations`: pydantic must resolve the
# Annotated[...] constraints below at class-construction time.
from typing import Annotated

from pydantic import BaseModel, Field

# Bounds mirror src.salary_model's plausibility filter, so the predictor cannot
# be asked about salaries the model was never trained on.
MIN_DESCRIPTION_LENGTH = 0
MAX_DESCRIPTION_LENGTH = 50_000
MAX_SKILLS_PER_REQUEST = 60


class PredictionRequest(BaseModel):
    """One hypothetical posting to price."""

    role_category: Annotated[str, Field(min_length=1, max_length=120)]
    seniority: Annotated[str, Field(min_length=1, max_length=120)]
    region: Annotated[str, Field(min_length=1, max_length=120)]
    contract_type: Annotated[str, Field(min_length=1, max_length=60)]
    contract_time: Annotated[str, Field(min_length=1, max_length=60)]
    skills: Annotated[list[str], Field(max_length=MAX_SKILLS_PER_REQUEST)] = []
    description_length: Annotated[
        int, Field(ge=MIN_DESCRIPTION_LENGTH, le=MAX_DESCRIPTION_LENGTH)
    ] = 1200


class PredictionResponse(BaseModel):
    """Model output, with the context needed to read it honestly."""

    predicted_salary: int
    lower_bound: int
    upper_bound: int
    model_name: str
    n_training_rows: int
    mae_gbp: float
    r2: float
    skills_recognised: list[str]
    skills_ignored: list[str]
