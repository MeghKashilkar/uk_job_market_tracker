"""Live data refresh: pull the newest Adzuna postings into the served dataset.

Runs as a background job because a full round-trip (collect -> clean -> classify
-> extract skills -> merge -> save) takes tens of seconds, far longer than a
request should hold a connection open.

Deliberately *incremental*: it collects one page per query and merges the result
into the existing processed dataset, deduped by Adzuna's job id. Rebuilding from
the raw CSV instead would be wrong on a deployed instance, where ``data/raw/``
is not shipped in the image - reprocessing would silently replace thousands of
rows with the few hundred just fetched.
"""

import os 
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any

import pandas as pd

from api.state import dataset_path, reset_caches
from src.collect_jobs import (
    DEFAULT_QUERIES,
    AdzunaCredentialsError,
    collect,
    dedupe_by_id,
    get_credentials,
)
from src.process_data import load_processed, process_frame, save_processed

# One page per query keeps a refresh to ~6 API calls and ~30s wall time. The
# collector already sorts newest-first, so a page is the freshest slice.
PAGES_PER_QUERY = 1
DEFAULT_COOLDOWN_SECONDS = 300

IDLE = "idle"
RUNNING = "running"
DONE = "done"
FAILED = "failed"


@dataclass
class RefreshState:
    """Progress of the most recent refresh, polled by the UI."""

    status: str = IDLE
    message: str = "No refresh has run yet."
    added: int = 0
    total: int = 0
    started_at: float | None = None
    finished_at: float | None = None

    def as_dict(self) -> dict[str, Any]:
        """Serializable snapshot, with a cooldown hint for the client."""
        payload = asdict(self)
        payload["available"] = is_available()
        payload["cooldown_remaining"] = cooldown_remaining()
        return payload


@dataclass
class _Guard:
    """Serializes refreshes and enforces the cooldown between them."""

    lock: threading.Lock = field(default_factory=threading.Lock)
    last_finished: float = 0.0


_state = RefreshState()
_guard = _Guard()


def is_available() -> bool:
    """Whether Adzuna credentials are configured for this process.

    Delegates to the collector's own resolution so a local ``.env`` and a
    Render environment variable are treated identically - otherwise the button
    would be hidden locally despite the keys being present.
    """
    try:
        get_credentials()
    except AdzunaCredentialsError:
        return False
    return True


def cooldown_seconds() -> int:
    """Minimum gap between refreshes, protecting the Adzuna free-tier quota."""
    try:
        return int(os.environ.get("REFRESH_COOLDOWN_SECONDS", DEFAULT_COOLDOWN_SECONDS))
    except ValueError:
        return DEFAULT_COOLDOWN_SECONDS


def cooldown_remaining() -> int:
    """Seconds left before another refresh is allowed."""
    if not _guard.last_finished:
        return 0
    elapsed = time.time() - _guard.last_finished
    return max(0, int(cooldown_seconds() - elapsed))


def get_state() -> dict[str, Any]:
    """Current refresh state for the status endpoint."""
    return _state.as_dict()


def is_running() -> bool:
    """Whether a refresh is in flight."""
    return _state.status == RUNNING


def merge_into_dataset(new_raw: pd.DataFrame) -> tuple[int, int]:
    """Process freshly-collected rows and merge them into the served dataset.

    Returns ``(rows_added, total_rows)``. Existing rows win on an id collision so
    the original ``collected_at`` - and therefore the trend charts - stay honest.
    """
    path = dataset_path()
    existing = load_processed(path) if path.exists() else pd.DataFrame()

    if new_raw.empty:
        return 0, len(existing)

    processed = process_frame(new_raw, source="adzuna refresh")

    combined = processed if existing.empty else pd.concat([existing, processed], ignore_index=True)
    combined = dedupe_by_id(combined)
    save_processed(combined, path)
    return len(combined) - len(existing), len(combined)


def run_refresh() -> None:
    """Collect, merge, and swap in the new dataset. Safe to call in a thread."""
    if not _guard.lock.acquire(blocking=False):
        return  # another refresh is already running

    try:
        _state.status = RUNNING
        _state.message = "Fetching the latest postings from Adzuna…"
        _state.started_at = time.time()
        _state.finished_at = None

        new_raw = collect(list(DEFAULT_QUERIES), max_pages=PAGES_PER_QUERY)
        _state.message = "Extracting skills and merging…"

        added, total = merge_into_dataset(new_raw)
        reset_caches()  # next request re-reads the dataset from disk

        _state.added = added
        _state.total = total
        _state.status = DONE
        _state.message = (
            f"Added {added} new posting{'s' if added != 1 else ''} "
            f"({total} total)."
            if added
            else f"Already up to date - no new postings ({total} total)."
        )
    except Exception as exc:
        _state.status = FAILED
        _state.message = f"Refresh failed: {exc}"
    finally:
        _state.finished_at = time.time()
        _guard.last_finished = time.time()
        _guard.lock.release()


def start_refresh() -> None:
    """Kick off :func:`run_refresh` on a daemon thread."""
    threading.Thread(target=run_refresh, name="adzuna-refresh", daemon=True).start()
