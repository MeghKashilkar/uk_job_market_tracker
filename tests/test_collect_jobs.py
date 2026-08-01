"""Tests for Adzuna collection: region extraction and id-safe deduplication."""

import pandas as pd

from src.collect_jobs import dedupe_by_id, extract_region, flatten_result


def test_extract_region_takes_the_broad_region_not_the_neighbourhood():
    """Area runs broad -> specific; the last element is a neighbourhood."""
    assert extract_region(["UK", "London", "Central London", "The City"]) == "London"
    assert extract_region(["UK", "Northern Ireland", "Belfast"]) == "Northern Ireland"


def test_extract_region_handles_short_and_empty_areas():
    assert extract_region(["UK"]) == "UK"
    assert extract_region([]) is None


def test_flatten_result_survives_missing_nested_objects():
    row = flatten_result({"id": "1", "title": " Data Analyst "}, query="data analyst")
    assert row["title"] == "Data Analyst"
    assert row["company"] == ""
    assert row["region"] is None


def test_dedupe_by_id_matches_int_and_string_ids():
    """The bug this guards: CSV round-trips turn str ids into int64."""
    df = pd.DataFrame(
        [
            {"id": 4802504178, "collected_at": "2026-08-01T13:00:00Z"},
            {"id": "4802504178", "collected_at": "2026-08-01T17:00:00Z"},
        ]
    )
    assert len(dedupe_by_id(df)) == 1


def test_dedupe_by_id_keeps_the_earliest_sighting():
    df = pd.DataFrame(
        [
            {"id": "a", "collected_at": "2026-08-05T00:00:00Z"},
            {"id": "a", "collected_at": "2026-08-01T00:00:00Z"},
        ]
    )
    assert dedupe_by_id(df)["collected_at"].iloc[0].startswith("2026-08-01")


def test_dedupe_by_id_without_an_id_column_is_a_no_op():
    df = pd.DataFrame([{"title": "Data Analyst"}])
    assert len(dedupe_by_id(df)) == 1
