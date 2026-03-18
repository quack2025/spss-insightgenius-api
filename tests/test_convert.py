"""Test convert endpoint."""



def test_convert_csv(client, auth_headers, test_sav_bytes):
    """POST /v1/convert to CSV → downloadable file."""
    response = client.post(
        "/v1/convert",
        headers=auth_headers,
        files={"file": ("survey.sav", test_sav_bytes, "application/octet-stream")},
        data={"target_format": "csv", "apply_labels": "true"},
    )
    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    assert "survey.csv" in response.headers.get("content-disposition", "")
    # Verify CSV content
    content = response.content.decode("utf-8-sig")
    assert "gender" in content.lower() or "Gender" in content or "Male" in content


def test_convert_xlsx(client, auth_headers, test_sav_bytes):
    """POST /v1/convert to Excel → downloadable .xlsx."""
    response = client.post(
        "/v1/convert",
        headers=auth_headers,
        files={"file": ("survey.sav", test_sav_bytes, "application/octet-stream")},
        data={"target_format": "xlsx", "apply_labels": "true", "include_metadata_sheet": "true"},
    )
    assert response.status_code == 200
    assert "spreadsheetml" in response.headers["content-type"]
    assert len(response.content) > 100  # Not empty


def test_convert_parquet(client, auth_headers, test_sav_bytes):
    """POST /v1/convert to Parquet → downloadable file (or 500 if pyarrow missing)."""
    import pytest
    try:
        import pyarrow
        has_pyarrow = True
    except ImportError:
        has_pyarrow = False

    response = client.post(
        "/v1/convert",
        headers=auth_headers,
        files={"file": ("survey.sav", test_sav_bytes, "application/octet-stream")},
        data={"target_format": "parquet", "apply_labels": "false"},
    )
    if has_pyarrow:
        assert response.status_code == 200
        assert len(response.content) > 100
    else:
        assert response.status_code == 500  # pyarrow not installed


def test_convert_invalid_format(client, auth_headers, test_sav_bytes):
    """POST /v1/convert with unsupported format → 400."""
    response = client.post(
        "/v1/convert",
        headers=auth_headers,
        files={"file": ("survey.sav", test_sav_bytes, "application/octet-stream")},
        data={"target_format": "json"},
    )
    assert response.status_code == 400
