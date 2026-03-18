"""Test authentication and authorization."""


def test_no_auth(client):
    """Request without auth → 401."""
    response = client.post(
        "/v1/metadata",
        files={"file": ("test.sav", b"dummy", "application/octet-stream")},
    )
    assert response.status_code == 401
    data = response.json()
    assert data["detail"]["code"] == "UNAUTHORIZED"


def test_invalid_key(client):
    """Request with wrong key → 401."""
    response = client.post(
        "/v1/metadata",
        headers={"Authorization": "Bearer sk_test_wrong_key_999"},
        files={"file": ("test.sav", b"dummy", "application/octet-stream")},
    )
    assert response.status_code == 401


def test_invalid_format(client):
    """Request with non-sk_ key → 401."""
    response = client.post(
        "/v1/metadata",
        headers={"Authorization": "Bearer not_a_valid_key"},
        files={"file": ("test.sav", b"dummy", "application/octet-stream")},
    )
    assert response.status_code == 401


def test_valid_auth(client, auth_headers, test_sav_bytes):
    """Request with valid key → 200."""
    response = client.post(
        "/v1/metadata",
        headers=auth_headers,
        files={"file": ("test.sav", test_sav_bytes, "application/octet-stream")},
    )
    assert response.status_code == 200
