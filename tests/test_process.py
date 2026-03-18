"""Test process endpoint — the main pipeline."""

import json


def test_process_with_operations(client, auth_headers, test_sav_bytes):
    """POST /v1/process with explicit operations → full results."""
    operations = json.dumps([
        {"type": "frequency", "variable": "gender"},
        {"type": "frequency", "variable": "satisfaction"},
        {"type": "nps", "variable": "recommend"},
    ])
    response = client.post(
        "/v1/process",
        headers=auth_headers,
        files={"file": ("survey.sav", test_sav_bytes, "application/octet-stream")},
        data={"operations": operations},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True

    data = body["data"]

    # Metadata present
    assert data["metadata"]["n_cases"] == 100
    assert data["metadata"]["n_variables"] == 5

    # 3 operations → 3 results
    assert len(data["results"]) == 3

    # Check all succeeded
    for result in data["results"]:
        assert result["status"] == "success", f"Operation {result['operation_id']} failed: {result.get('error')}"
        assert result["data"] is not None

    # Check NPS result shape
    nps_result = next(r for r in data["results"] if r["type"] == "nps")
    assert "nps_score" in nps_result["data"]
    assert "promoters" in nps_result["data"]


def test_process_auto_plan(client, auth_headers, test_sav_bytes):
    """POST /v1/process without operations → auto-planned results."""
    response = client.post(
        "/v1/process",
        headers=auth_headers,
        files={"file": ("survey.sav", test_sav_bytes, "application/octet-stream")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    # Auto planner should generate at least some operations
    data = body["data"]
    assert data["metadata"]["n_cases"] == 100


def test_process_with_weight(client, auth_headers, test_sav_bytes):
    """POST /v1/process with default weight → operations use weight."""
    operations = json.dumps([
        {"type": "frequency", "variable": "gender"},
    ])
    response = client.post(
        "/v1/process",
        headers=auth_headers,
        files={"file": ("survey.sav", test_sav_bytes, "application/octet-stream")},
        data={"operations": operations, "weight": "weight_var"},
    )
    assert response.status_code == 200
    body = response.json()
    result = body["data"]["results"][0]
    assert result["status"] == "success"


def test_process_invalid_operations(client, auth_headers, test_sav_bytes):
    """POST /v1/process with invalid operations JSON → 400."""
    response = client.post(
        "/v1/process",
        headers=auth_headers,
        files={"file": ("survey.sav", test_sav_bytes, "application/octet-stream")},
        data={"operations": "not json"},
    )
    assert response.status_code == 400
