"""Shared client for the async /api/extract job flow used by the test suite."""
import time

import requests

API = "http://localhost:8001/api"


def start_extract(file_tuple, engine: str | None = None) -> requests.Response:
    """POST /api/extract — returns the raw response (202 with a job_id, or 4xx)."""
    data = {"engine": engine} if engine else None
    return requests.post(f"{API}/extract", files={"file": file_tuple}, data=data, timeout=60)


def wait_for_extract(job_id: str, timeout: float = 420) -> dict:
    deadline = time.time() + timeout
    last = {}
    while time.time() < deadline:
        res = requests.get(f"{API}/extract/{job_id}", timeout=30)
        res.raise_for_status()
        last = res.json()
        if last["status"] == "done":
            return last
        if last["status"] == "error":
            raise AssertionError(f"extract job failed: {last}")
        time.sleep(2)
    raise AssertionError(f"extract job timed out after {timeout}s: {last}")


def extract(file_tuple, engine: str | None = None, timeout: float = 420) -> dict:
    """Start a job and block until the text is ready. Returns {id, text, engine}."""
    res = start_extract(file_tuple, engine)
    assert res.status_code == 202, f"unexpected start response: {res.status_code} {res.text}"
    return wait_for_extract(res.json()["job_id"], timeout)
