"""Test metadata endpoint."""



def test_metadata(client, auth_headers, test_sav_bytes):
    """POST /v1/metadata with valid .sav → metadata response."""
    response = client.post(
        "/v1/metadata",
        headers=auth_headers,
        files={"file": ("survey.sav", test_sav_bytes, "application/octet-stream")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True

    data = body["data"]
    assert data["n_cases"] == 100
    assert data["n_variables"] == 5
    assert len(data["variables"]) == 5

    # Check variable info
    var_names = [v["name"] for v in data["variables"]]
    assert "gender" in var_names
    assert "satisfaction" in var_names

    # Check labels
    gender_var = next(v for v in data["variables"] if v["name"] == "gender")
    assert gender_var["label"] == "Gender"
    assert gender_var["type"] == "numeric"

    # Check value labels
    assert gender_var["value_labels"] is not None
    assert "1.0" in gender_var["value_labels"] or "1" in gender_var["value_labels"]

    # Weight detection
    assert "weight_var" in data.get("detected_weights", [])

    # Meta
    assert body["meta"]["processing_time_ms"] >= 0


def test_metadata_invalid_file(client, auth_headers):
    """POST /v1/metadata with non-.sav file → 400."""
    response = client.post(
        "/v1/metadata",
        headers=auth_headers,
        files={"file": ("data.csv", b"a,b,c\n1,2,3", "text/csv")},
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "INVALID_FILE_FORMAT"
