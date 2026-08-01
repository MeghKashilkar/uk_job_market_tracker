"""Self-sourced data collection from the Adzuna Job Search API.

Adzuna is free at this volume (developer sign-up, no scraping ToS risk):
https://developer.adzuna.com/

Setup:
    1. Sign up at https://developer.adzuna.com/ (free, instant).
    2. Copy your app_id and app_key into a ``.env`` file in the project root::

        ADZUNA_APP_ID=your_app_id
        ADZUNA_APP_KEY=your_app_key

Usage::

    python -m src.collect_jobs
    python -m src.collect_jobs --queries "data analyst,data engineer" --pages 3

Re-running this on different days is the point: each run appends newly-seen
postings (deduped by Adzuna's job id) with a ``collected_at`` timestamp, so
reports built later show genuine week-over-week demand trends instead of a
single static snapshot.
"""

from __future__ import annotations

import argparse
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]

COUNTRY = "gb"
BASE_URL = f"https://api.adzuna.com/v1/api/jobs/{COUNTRY}/search"
RESULTS_PER_PAGE = 50  # Adzuna's maximum
REQUEST_DELAY_SECONDS = 1.0  # be a polite API citizen
REQUEST_TIMEOUT_SECONDS = 15
RATE_LIMIT_BACKOFF_SECONDS = 10
MAX_RATE_LIMIT_RETRIES = 3

DEFAULT_QUERIES = (
    "data analyst",
    "data scientist",
    "data engineer",
    "machine learning engineer",
    "business intelligence",
    "analytics engineer",
)

OUTPUT_PATH = ROOT / "data" / "raw" / "adzuna_jobs.csv"

SCHEMA_COLUMNS = [
    "id",
    "title",
    "company",
    "location",
    "region",
    "description",
    "salary_min",
    "salary_max",
    "salary_is_predicted",
    "contract_type",
    "contract_time",
    "category",
    "created",
    "redirect_url",
    "query",
    "collected_at",
]


class AdzunaCredentialsError(RuntimeError):
    """Raised when the Adzuna app id/key are missing from the environment."""


def get_credentials() -> tuple[str, str]:
    """Read Adzuna credentials from the environment (loading ``.env`` first).

    Read at call time rather than import time so a ``.env`` created after this
    module is imported — and monkeypatched values in tests — still apply.
    """
    load_dotenv(ROOT / ".env")
    app_id = os.environ.get("ADZUNA_APP_ID")
    app_key = os.environ.get("ADZUNA_APP_KEY")
    if not app_id or not app_key:
        raise AdzunaCredentialsError(
            "Missing ADZUNA_APP_ID / ADZUNA_APP_KEY. Sign up free at "
            "https://developer.adzuna.com/ and put them in a .env file "
            "(see the docstring at the top of src/collect_jobs.py)."
        )
    return app_id, app_key


def extract_region(area: list[str]) -> str | None:
    """Pick the broad UK region from Adzuna's ``area`` hierarchy.

    ``area`` runs broad -> specific, e.g.
    ``['UK', 'London', 'Central London', 'The City']``. Index 1 is the region
    ("London", "Northern Ireland", "South East England"); the last element is a
    neighbourhood, which would give the salary model hundreds of one-hot
    columns that cannot generalise.
    """
    if not area:
        return None
    return area[1] if len(area) > 1 else area[0]


def flatten_result(raw: dict, query: str) -> dict:
    """Flatten one Adzuna result object into a flat row matching ``SCHEMA_COLUMNS``."""
    location = raw.get("location") or {}
    area = location.get("area") or []
    return {
        "id": raw.get("id"),
        "title": (raw.get("title") or "").strip(),
        "company": (raw.get("company") or {}).get("display_name", ""),
        "location": location.get("display_name", ""),
        "region": extract_region(area),
        "description": raw.get("description", ""),
        "salary_min": raw.get("salary_min"),
        "salary_max": raw.get("salary_max"),
        "salary_is_predicted": raw.get("salary_is_predicted"),
        "contract_type": raw.get("contract_type"),
        "contract_time": raw.get("contract_time"),
        "category": (raw.get("category") or {}).get("label", ""),
        "created": raw.get("created"),
        "redirect_url": raw.get("redirect_url"),
        "query": query,
        "collected_at": datetime.now(UTC).isoformat(),
    }


def fetch_query(query: str, max_pages: int, where: str = "UK") -> list[dict]:
    """Page through Adzuna results for a single search query."""
    app_id, app_key = get_credentials()
    results: list[dict] = []

    for page in range(1, max_pages + 1):
        params: dict[str, str | int] = {
            "app_id": app_id,
            "app_key": app_key,
            "results_per_page": RESULTS_PER_PAGE,
            "what": query,
            "where": where,
            "content-type": "application/json",
        }

        for attempt in range(MAX_RATE_LIMIT_RETRIES):
            response = requests.get(
                f"{BASE_URL}/{page}", params=params, timeout=REQUEST_TIMEOUT_SECONDS
            )
            if response.status_code != 429:
                break
            print(
                f"[collect_jobs] Rate limited on '{query}' page {page} — "
                f"backing off {RATE_LIMIT_BACKOFF_SECONDS}s "
                f"(attempt {attempt + 1}/{MAX_RATE_LIMIT_RETRIES})."
            )
            time.sleep(RATE_LIMIT_BACKOFF_SECONDS)
        else:
            print(f"[collect_jobs] Still rate limited on '{query}' page {page} — skipping.")
            continue

        response.raise_for_status()
        batch = response.json().get("results", [])
        if not batch:
            break

        results.extend(flatten_result(item, query) for item in batch)
        print(f"[collect_jobs] '{query}' page {page}: +{len(batch)} (running total {len(results)})")
        time.sleep(REQUEST_DELAY_SECONDS)

    return results


def collect(queries: list[str], max_pages: int, where: str = "UK") -> pd.DataFrame:
    """Collect every query, skipping (not failing on) any query that errors."""
    rows: list[dict] = []
    for query in queries:
        try:
            rows.extend(fetch_query(query, max_pages=max_pages, where=where))
        except requests.exceptions.RequestException as exc:
            print(f"[collect_jobs] Request error on '{query}': {exc} — skipping this query.")
    return pd.DataFrame(rows, columns=SCHEMA_COLUMNS)


def dedupe_by_id(df: pd.DataFrame) -> pd.DataFrame:
    """Collapse repeat sightings of a posting, keeping the earliest ``collected_at``.

    Ids are normalised to ``str`` before comparing, which is the whole point of
    this helper: Adzuna sends ids as strings, but a CSV round-trip reads them
    back as int64. Comparing the two directly leaves ``4802504178`` and
    ``"4802504178"`` looking distinct, so every re-collection silently doubles
    the overlapping rows.
    """
    if "id" not in df.columns:
        return df.reset_index(drop=True)

    normalised = df.assign(id=df["id"].astype(str))
    if "collected_at" in normalised.columns:
        normalised = normalised.sort_values("collected_at", kind="stable")
    return normalised.drop_duplicates(subset="id", keep="first").reset_index(drop=True)


def merge_and_save(new_df: pd.DataFrame, output_path: Path = OUTPUT_PATH) -> tuple[int, int]:
    """Append genuinely-new rows to the dataset, deduped by Adzuna's job id.

    Keeps the earliest ``collected_at`` per id so "first seen" stays accurate on
    re-runs. Returns ``(rows_added, total_rows)``.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if output_path.exists():
        existing = pd.read_csv(output_path)
        combined = pd.concat([existing, new_df], ignore_index=True)
    else:
        existing = pd.DataFrame(columns=SCHEMA_COLUMNS)
        combined = new_df

    combined = dedupe_by_id(combined)
    combined.to_csv(output_path, index=False)
    return len(combined) - len(existing), len(combined)


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Collect UK data/tech job postings from Adzuna",
    )
    parser.add_argument(
        "--queries",
        default=",".join(DEFAULT_QUERIES),
        help="Comma-separated search terms",
    )
    parser.add_argument("--where", default="UK", help="Adzuna location filter, e.g. 'London'")
    parser.add_argument(
        "--pages", type=int, default=5, help="Max pages (50 results each) per query"
    )
    parser.add_argument("--output", default=str(OUTPUT_PATH))
    args = parser.parse_args()

    queries = [query.strip() for query in args.queries.split(",") if query.strip()]
    print(
        f"[collect_jobs] Collecting for queries={queries} "
        f"where='{args.where}' pages={args.pages}"
    )

    new_df = collect(queries, max_pages=args.pages, where=args.where)
    added, total = merge_and_save(new_df, output_path=Path(args.output))

    print(f"[collect_jobs] Done. +{added} new rows this run, {total} total rows in {args.output}")
    print(
        "[collect_jobs] Re-run this every few days (see the README's 'Automate collection' "
        "section) to build up week-over-week trend data."
    )


if __name__ == "__main__":
    main()
