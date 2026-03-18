"""Test frequency endpoint."""



def test_frequency(client, auth_headers, test_sav_bytes):
    """POST /v1/frequency with valid variable → frequency table."""
    response = client.post(
        "/v1/frequency",
        headers=auth_headers,
        files={"file": ("survey.sav", test_sav_bytes, "application/octet-stream")},
        data={"variable": "gender"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True

    data = body["data"]
    assert data["variable"] == "gender"
    assert data["label"] == "Gender"
    assert data["base"] == 100
    assert len(data["frequencies"]) == 2

    # Check frequencies sum to ~100%
    total_pct = sum(f["percentage"] for f in data["frequencies"])
    assert 99.0 <= total_pct <= 101.0

    # Check value labels are applied
    labels = {f["label"] for f in data["frequencies"]}
    assert "Male" in labels or "Female" in labels


def test_frequency_with_weight(client, auth_headers, test_sav_bytes):
    """POST /v1/frequency with weight → weighted counts."""
    response = client.post(
        "/v1/frequency",
        headers=auth_headers,
        files={"file": ("survey.sav", test_sav_bytes, "application/octet-stream")},
        data={"variable": "satisfaction", "weight": "weight_var"},
    )
    assert response.status_code == 200
    body = response.json()
    data = body["data"]
    assert data["variable"] == "satisfaction"
    assert len(data["frequencies"]) == 5  # 5-point scale


def test_frequency_variable_not_found(client, auth_headers, test_sav_bytes):
    """POST /v1/frequency with nonexistent variable → 400."""
    response = client.post(
        "/v1/frequency",
        headers=auth_headers,
        files={"file": ("survey.sav", test_sav_bytes, "application/octet-stream")},
        data={"variable": "nonexistent_var"},
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "VARIABLE_NOT_FOUND"
