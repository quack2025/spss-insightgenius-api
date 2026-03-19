"""Test health endpoint."""


def test_health(client):
    response = client.get("/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["version"] == "1.0.0"
    assert data["engine"] == "quantipymrx"
    assert "quantipymrx_available" in data


def test_root(client):
    response = client.get("/")
    assert response.status_code == 200
    # Root now serves HTML frontend or JSON fallback
    content_type = response.headers.get("content-type", "")
    if "html" in content_type:
        assert "InsightGenius" in response.text
    else:
        data = response.json()
        assert "docs" in data
