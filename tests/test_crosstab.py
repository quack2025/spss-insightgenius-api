"""Test crosstab endpoint."""

import io
import json


def test_crosstab(client, auth_headers, test_sav_bytes):
    """POST /v1/crosstab with valid spec → crosstab with significance."""
    spec = json.dumps({"row": "satisfaction", "col": "gender", "significance_level": 0.95})
    response = client.post(
        "/v1/crosstab",
        headers=auth_headers,
        files={"file": ("survey.sav", test_sav_bytes, "application/octet-stream")},
        data={"spec": spec},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True

    data = body["data"]
    assert data["row_variable"] == "satisfaction"
    assert data["col_variable"] == "gender"
    assert data["significance_level"] == 0.95
    assert len(data["table"]) > 0
    assert len(data["col_labels"]) > 0

    # Check table structure: each row has row_value + column entries
    first_row = data["table"][0]
    assert "row_value" in first_row
    assert "row_label" in first_row

    # Check at least one column has significance_letters field
    col_keys = [k for k in first_row.keys() if k not in ("row_value", "row_label")]
    assert len(col_keys) > 0
    cell = first_row[col_keys[0]]
    assert "count" in cell
    assert "percentage" in cell
    assert "significance_letters" in cell


def test_crosstab_invalid_spec(client, auth_headers, test_sav_bytes):
    """POST /v1/crosstab with invalid JSON → 400."""
    response = client.post(
        "/v1/crosstab",
        headers=auth_headers,
        files={"file": ("survey.sav", test_sav_bytes, "application/octet-stream")},
        data={"spec": "not json"},
    )
    assert response.status_code == 400


def test_crosstab_missing_fields(client, auth_headers, test_sav_bytes):
    """POST /v1/crosstab with missing row/col → 400."""
    spec = json.dumps({"row": "satisfaction"})  # missing col
    response = client.post(
        "/v1/crosstab",
        headers=auth_headers,
        files={"file": ("survey.sav", test_sav_bytes, "application/octet-stream")},
        data={"spec": spec},
    )
    assert response.status_code == 400
