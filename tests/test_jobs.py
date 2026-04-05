"""Tests for async job lifecycle."""
import pytest
from shared.job_store import JobStore, JobStatus


def test_create_job():
    store = JobStore()
    job_id = store.create(user_id="demo", endpoint="/v1/tabulate", webhook_url=None)
    assert job_id
    assert len(job_id) == 36  # UUID


def test_get_job_initial_status():
    store = JobStore()
    job_id = store.create(user_id="demo", endpoint="/v1/tabulate", webhook_url=None)
    job = store.get(job_id)
    assert job is not None
    assert job["status"] == JobStatus.PENDING
    assert job["endpoint"] == "/v1/tabulate"
    assert job["result"] is None


def test_update_status():
    store = JobStore()
    job_id = store.create(user_id="demo", endpoint="/v1/tabulate", webhook_url=None)
    store.update(job_id, status=JobStatus.RUNNING)
    job = store.get(job_id)
    assert job["status"] == JobStatus.RUNNING


def test_complete_with_result():
    store = JobStore()
    job_id = store.create(user_id="demo", endpoint="/v1/tabulate", webhook_url=None)
    store.complete(job_id, download_url="https://example.com/dl/abc123")
    job = store.get(job_id)
    assert job["status"] == JobStatus.DONE
    assert job["result"]["download_url"] == "https://example.com/dl/abc123"


def test_fail_with_error():
    store = JobStore()
    job_id = store.create(user_id="demo", endpoint="/v1/tabulate", webhook_url=None)
    store.fail(job_id, error_code="TIMEOUT", error_message="Processing exceeded 120s")
    job = store.get(job_id)
    assert job["status"] == JobStatus.FAILED
    assert job["result"]["error"]["code"] == "TIMEOUT"


def test_get_nonexistent_returns_none():
    store = JobStore()
    assert store.get("nonexistent-uuid") is None
