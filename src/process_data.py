"""End-to-end processing: raw collected postings -> cleaned, skill-tagged dataset.

Both the API and the salary model read the output of this step::

    data/raw/adzuna_jobs.csv (or a synthetic sample)
        -- clean_description / clean_title      (src.text_cleaning)
        -- classify_role / classify_seniority   (src.title_classification)
        -- extract_skills_batch                 (src.skill_extraction)
        --> data/processed/jobs_processed.csv

Usage::

    python -m src.process_data --input data/raw/adzuna_jobs.csv
    python -m src.process_data --input data/raw/sample_jobs_synthetic.csv \
        --output data/processed/jobs_processed_sample.csv
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

import pandas as pd

from src.skill_extraction import extract_skills_batch
from src.skills_taxonomy import skill_count_column, skill_count_columns, skill_to_category_map
from src.text_cleaning import clean_description, clean_title
from src.title_classification import add_classification_columns

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data" / "raw" / "adzuna_jobs.csv"
DEFAULT_OUTPUT = ROOT / "data" / "processed" / "jobs_processed.csv"

REQUIRED_INPUT_COLUMNS = ("title", "description")
SKILLS_SEPARATOR = "|"


def add_skill_category_counts(df: pd.DataFrame, skills_col: str = "skills") -> pd.DataFrame:
    """Add one ``n_<category>`` count column per taxonomy category, plus a total.

    Counts every category in a single pass over the skill lists rather than one
    ``apply`` per category, which matters once the taxonomy or dataset grows.
    """
    df = df.copy()
    category_of = skill_to_category_map()

    per_row = [
        Counter(category_of[skill] for skill in skills if skill in category_of)
        for skills in df[skills_col]
    ]
    counts = pd.DataFrame(per_row, index=df.index).fillna(0).astype(int)

    for column in skill_count_columns():
        df[column] = 0
    for category in counts.columns:
        df[skill_count_column(category)] = counts[category]

    df["n_skills_total"] = df[skills_col].map(len)
    return df


def add_salary_midpoint(df: pd.DataFrame) -> pd.DataFrame:
    """Coerce the salary bounds to numbers and derive their midpoint.

    A posting with only one bound still yields a midpoint (``mean`` skips NaN),
    which is deliberate - a stated floor is better signal than dropping the row.
    """
    df = df.copy()
    for column in ("salary_min", "salary_max"):
        df[column] = pd.to_numeric(df[column], errors="coerce") if column in df else pd.NA
    df["salary_midpoint"] = df[["salary_min", "salary_max"]].mean(axis=1)
    return df


def process(input_path: Path, output_path: Path) -> pd.DataFrame:
    """Run the full cleaning/classification/extraction pipeline and save the result."""
    df = pd.read_csv(input_path)
    print(f"[process_data] Loaded {len(df)} raw postings from {input_path}")
    print("[process_data] Extracting skills with spaCy PhraseMatcher (this can take a minute) ...")

    df = process_frame(df, source=str(input_path))
    save_processed(df, output_path)

    with_salary = df["salary_midpoint"].notna()
    print(f"[process_data] Saved {len(df)} processed rows to {output_path}")
    print(
        f"[process_data] Postings with salary data: {with_salary.sum()} "
        f"({with_salary.mean():.1%})"
    )
    return df


def process_frame(df: pd.DataFrame, source: str = "<frame>") -> pd.DataFrame:
    """Run the cleaning/classification/extraction transform on an in-memory frame.

    Split out from :func:`process` so the API's refresh job can process a small
    batch of newly-collected postings and merge them into the existing dataset,
    rather than re-running spaCy over every row it already has.
    """
    missing = [column for column in REQUIRED_INPUT_COLUMNS if column not in df.columns]
    if missing:
        raise ValueError(
            f"{source} is missing required column(s): {', '.join(missing)}. "
            "Expected data produced by src.collect_jobs or the synthetic sample script."
        )

    df = df.copy()
    df["title_clean"] = df["title"].map(clean_title)
    df["description_clean"] = df["description"].map(clean_description)
    df["description_length"] = df["description_clean"].str.len()

    df = add_classification_columns(df, title_col="title_clean")
    df["skills"] = extract_skills_batch(df["description_clean"])
    df = add_skill_category_counts(df)
    return add_salary_midpoint(df)


def save_processed(df: pd.DataFrame, output_path: Path) -> None:
    """Write the processed frame, flattening ``skills`` back to a CSV-safe string."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Skills are stored pipe-separated so the artifact stays a plain CSV;
    # load_processed splits them back into real lists.
    df.assign(skills=df["skills"].map(SKILLS_SEPARATOR.join)).to_csv(output_path, index=False)


def load_processed(path: Path | str = DEFAULT_OUTPUT) -> pd.DataFrame:
    """Read a processed CSV back with ``skills`` restored as a real list column."""
    df = pd.read_csv(path)
    df["skills"] = (
        df["skills"]
        .fillna("")
        .map(lambda value: [skill for skill in value.split(SKILLS_SEPARATOR) if skill])
    )
    return df


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Clean, classify, and skill-tag raw job postings",
    )
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()

    process(Path(args.input), Path(args.output))


if __name__ == "__main__":
    main()
