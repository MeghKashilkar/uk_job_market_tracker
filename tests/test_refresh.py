"""Tests for the incremental live-refresh merge.

The merge is the risky part: on a deployed instance ``data/raw/`` is not in the
image, so anything that rebuilds from raw would replace the whole dataset with
the handful of rows just fetched.
"""

import pandas as pd
import pytest

from api import refresh as refresh_service

pytest.importorskip("spacy", reason="spaCy required to process refreshed rows")


def _raw_row(job_id: str, title: str = "Data Engineer") -> dict:
    return {
        "id": job_id,
        "title": title,
        "company": "Acme",
        "location": "London",
        "region": "London",
        "description": "We need strong Python and SQL skills, plus AWS.",
        "salary_min": 60000,
        "salary_max": 70000,
        "salary_is_predicted": False,
        "contract_type": "permanent",
        "contract_time": "full_time",
        "category": "IT Jobs",
        "created": "2026-08-01T09:00:00Z",
        "redirect_url": "https://example.invalid/1",
        "query": "data engineer",
        "collected_at": "2026-08-01T10:00:00Z",
    }


@pytest.fixture()
def dataset(tmp_path, monkeypatch):
    """Point the refresh service at a throwaway dataset with one existing row."""
    path = tmp_path / "jobs_processed.csv"
    monkeypatch.setattr(refresh_service, "dataset_path", lambda: path)
    monkeypatch.setattr(refresh_service, "reset_caches", lambda: None)

    seed = refresh_service.process_frame(pd.DataFrame([_raw_row("existing-1")]))
    refresh_service.save_processed(seed, path)
    return path


def test_merge_appends_new_rows(dataset):
    added, total = refresh_service.merge_into_dataset(pd.DataFrame([_raw_row("new-1")]))
    assert (added, total) == (1, 2)


def test_merge_keeps_existing_rows(dataset):
    """Regression: a refresh must never shrink the dataset it merges into."""
    before = len(pd.read_csv(dataset))
    refresh_service.merge_into_dataset(pd.DataFrame([_raw_row("new-1")]))
    assert len(pd.read_csv(dataset)) > before


def test_merge_deduplicates_by_job_id(dataset):
    added, total = refresh_service.merge_into_dataset(pd.DataFrame([_raw_row("existing-1")]))
    assert (added, total) == (0, 1)


def test_merge_preserves_the_original_collected_at(dataset):
    """The first sighting wins, so week-over-week trends stay truthful."""
    repeat = _raw_row("existing-1")
    repeat["collected_at"] = "2026-09-09T10:00:00Z"
    refresh_service.merge_into_dataset(pd.DataFrame([repeat]))
    assert pd.read_csv(dataset)["collected_at"].iloc[0].startswith("2026-08-01")


def test_merge_with_nothing_collected_is_a_no_op(dataset):
    added, total = refresh_service.merge_into_dataset(pd.DataFrame())
    assert (added, total) == (0, 1)


def test_refreshed_rows_are_fully_processed(dataset):
    refresh_service.merge_into_dataset(pd.DataFrame([_raw_row("new-1")]))
    row = pd.read_csv(dataset).query("id == 'new-1'").iloc[0]
    assert row["role_category"] == "Data Engineer"
    assert "Python" in row["skills"]
    assert row["salary_midpoint"] == 65000


def test_is_available_is_false_without_credentials(monkeypatch):
    def boom():
        raise refresh_service.AdzunaCredentialsError("no keys configured")

    monkeypatch.setattr(refresh_service, "get_credentials", boom)
    assert refresh_service.is_available() is False


def test_is_available_is_true_with_credentials(monkeypatch):
    monkeypatch.setattr(refresh_service, "get_credentials", lambda: ("id", "key"))
    assert refresh_service.is_available() is True


def test_merge_deduplicates_across_a_csv_roundtrip(tmp_path, monkeypatch):
    """Regression: Adzuna sends ids as str, a CSV round-trip returns them as int64.

    Comparing the two unnormalised left both copies in the dataset — a real
    refresh duplicated 295 postings before this was fixed.
    """
    path = tmp_path / "numeric_ids.csv"
    monkeypatch.setattr(refresh_service, "dataset_path", lambda: path)
    monkeypatch.setattr(refresh_service, "reset_caches", lambda: None)

    numeric_id = "4802504178"  # Adzuna ids look numeric but arrive as strings
    seed = refresh_service.process_frame(pd.DataFrame([_raw_row(numeric_id)]))
    refresh_service.save_processed(seed, path)

    stored = pd.read_csv(path)["id"].iloc[0]
    assert not isinstance(stored, str), "round-trip should have coerced the id to int64"

    added, total = refresh_service.merge_into_dataset(pd.DataFrame([_raw_row(numeric_id)]))
    assert (added, total) == (0, 1)
    assert pd.read_csv(path)["id"].duplicated().sum() == 0
