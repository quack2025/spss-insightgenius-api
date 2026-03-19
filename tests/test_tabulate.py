"""Tests for POST /v1/tabulate endpoint."""

import json
import io
from openpyxl import load_workbook


def test_tabulate_basic(client, auth_headers, test_sav_bytes):
    """Tabulate satisfaction × gender → Excel with 1 sheet."""
    spec = json.dumps({
        "banner": "gender",
        "stubs": ["satisfaction"],
        "significance_level": 0.95,
    })
    resp = client.post(
        "/v1/tabulate",
        headers=auth_headers,
        files={"file": ("test.sav", test_sav_bytes, "application/octet-stream")},
        data={"spec": spec},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert "X-Stubs-Total" in resp.headers
    assert resp.headers["X-Stubs-Total"] == "1"
    assert resp.headers["X-Stubs-Success"] == "1"

    # Verify Excel content
    wb = load_workbook(io.BytesIO(resp.content))
    assert "Summary" in wb.sheetnames
    assert "satisfaction" in wb.sheetnames

    # Check summary sheet has content
    ws = wb["Summary"]
    assert ws.cell(row=1, column=1).value is not None  # Title

    # Check crosstab sheet has data
    ws_ct = wb["satisfaction"]
    assert "satisfaction" in ws_ct.cell(row=1, column=1).value  # Title row
    assert ws_ct.cell(row=5, column=1).value == "Base (N)"  # Base row


def test_tabulate_all_stubs(client, auth_headers, test_sav_bytes):
    """Tabulate with stubs=_all_ auto-selects variables with value labels."""
    spec = json.dumps({
        "banner": "gender",
        "stubs": ["_all_"],
    })
    resp = client.post(
        "/v1/tabulate",
        headers=auth_headers,
        files={"file": ("test.sav", test_sav_bytes, "application/octet-stream")},
        data={"spec": spec},
    )
    assert resp.status_code == 200
    # Should include age_group and satisfaction (both have value labels)
    # but not gender (it's the banner) and not recommend/weight_var (no labels)
    total = int(resp.headers["X-Stubs-Total"])
    assert total >= 2  # age_group + satisfaction at minimum


def test_tabulate_with_nets(client, auth_headers, test_sav_bytes):
    """Tabulate with net definitions (Top 2 Box)."""
    spec = json.dumps({
        "banner": "gender",
        "stubs": ["satisfaction"],
        "nets": {
            "satisfaction": {
                "Top 2 Box": [4, 5],
                "Bottom 2 Box": [1, 2],
            },
        },
    })
    resp = client.post(
        "/v1/tabulate",
        headers=auth_headers,
        files={"file": ("test.sav", test_sav_bytes, "application/octet-stream")},
        data={"spec": spec},
    )
    assert resp.status_code == 200
    wb = load_workbook(io.BytesIO(resp.content))
    ws = wb["satisfaction"]

    # Find "Nets" label in column A
    nets_found = False
    for row in ws.iter_rows(min_col=1, max_col=1):
        if row[0].value == "Nets":
            nets_found = True
            break
    assert nets_found, "Nets section not found in Excel"


def test_tabulate_with_weight(client, auth_headers, test_sav_bytes):
    """Tabulate with weight variable."""
    spec = json.dumps({
        "banner": "gender",
        "stubs": ["satisfaction"],
        "weight": "weight_var",
    })
    resp = client.post(
        "/v1/tabulate",
        headers=auth_headers,
        files={"file": ("test.sav", test_sav_bytes, "application/octet-stream")},
        data={"spec": spec},
    )
    assert resp.status_code == 200
    wb = load_workbook(io.BytesIO(resp.content))
    ws = wb["satisfaction"]
    # Check significance note mentions weight
    sig_note = ws.cell(row=2, column=1).value
    assert "weight_var" in sig_note


def test_tabulate_missing_banner(client, auth_headers, test_sav_bytes):
    """Missing banner → 400."""
    spec = json.dumps({"stubs": ["satisfaction"]})
    resp = client.post(
        "/v1/tabulate",
        headers=auth_headers,
        files={"file": ("test.sav", test_sav_bytes, "application/octet-stream")},
        data={"spec": spec},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "INVALID_SPEC"


def test_tabulate_invalid_banner(client, auth_headers, test_sav_bytes):
    """Banner variable not found → 400."""
    spec = json.dumps({"banner": "NONEXISTENT", "stubs": ["satisfaction"]})
    resp = client.post(
        "/v1/tabulate",
        headers=auth_headers,
        files={"file": ("test.sav", test_sav_bytes, "application/octet-stream")},
        data={"spec": spec},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "VARIABLE_NOT_FOUND"


def test_tabulate_invalid_stub(client, auth_headers, test_sav_bytes):
    """Stub variable not found → 400."""
    spec = json.dumps({"banner": "gender", "stubs": ["Q999"]})
    resp = client.post(
        "/v1/tabulate",
        headers=auth_headers,
        files={"file": ("test.sav", test_sav_bytes, "application/octet-stream")},
        data={"spec": spec},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "VARIABLE_NOT_FOUND"
