"""Tests for POST /v1/tabulate endpoint — including Tier 1 features."""

import json
import io
from openpyxl import load_workbook


def test_tabulate_basic(client, auth_headers, test_sav_bytes):
    """Tabulate satisfaction x gender -> Excel with 1 sheet."""
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
    assert resp.headers["X-Stubs-Total"] == "1"
    assert resp.headers["X-Stubs-Success"] == "1"

    wb = load_workbook(io.BytesIO(resp.content))
    assert "Summary" in wb.sheetnames
    assert "satisfaction" in wb.sheetnames

    ws_ct = wb["satisfaction"]
    assert "satisfaction" in ws_ct.cell(row=1, column=1).value


def test_tabulate_all_stubs(client, auth_headers, test_sav_bytes):
    """Tabulate with stubs=_all_ auto-selects variables with value labels."""
    spec = json.dumps({"banner": "gender", "stubs": ["_all_"]})
    resp = client.post(
        "/v1/tabulate",
        headers=auth_headers,
        files={"file": ("test.sav", test_sav_bytes, "application/octet-stream")},
        data={"spec": spec},
    )
    assert resp.status_code == 200
    total = int(resp.headers["X-Stubs-Total"])
    assert total >= 2


def test_tabulate_with_nets(client, auth_headers, test_sav_bytes):
    """Tabulate with net definitions (Top 2 Box)."""
    spec = json.dumps({
        "banner": "gender",
        "stubs": ["satisfaction"],
        "nets": {"satisfaction": {"Top 2 Box": [4, 5], "Bottom 2 Box": [1, 2]}},
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
    nets_found = any(row[0].value == "Nets" for row in ws.iter_rows(min_col=1, max_col=1))
    assert nets_found, "Nets section not found in Excel"


def test_tabulate_with_weight(client, auth_headers, test_sav_bytes):
    """T1-4: Tabulate with weight shows dual bases."""
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
    # Check for dual bases
    found_weighted = False
    found_unweighted = False
    for row in ws.iter_rows(min_col=1, max_col=1, max_row=10):
        val = row[0].value or ""
        if "weighted" in val.lower():
            found_weighted = True
        if "unweighted" in val.lower():
            found_unweighted = True
    assert found_weighted, "Weighted base row not found"
    assert found_unweighted, "Unweighted base row not found"


def test_tabulate_means(client, auth_headers, test_sav_bytes):
    """T1-1: Means row with T-test."""
    spec = json.dumps({
        "banner": "gender",
        "stubs": ["satisfaction"],
        "include_means": True,
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
    # Find "Mean" label
    mean_found = False
    for row in ws.iter_rows(min_col=1, max_col=1):
        if row[0].value == "Mean":
            mean_found = True
            break
    assert mean_found, "Mean row not found in Excel"


def test_tabulate_multiple_banners(client, auth_headers, test_sav_bytes):
    """T1-2: Multiple banners side-by-side."""
    spec = json.dumps({
        "banners": ["gender", "age_group"],
        "stubs": ["satisfaction"],
    })
    resp = client.post(
        "/v1/tabulate",
        headers=auth_headers,
        files={"file": ("test.sav", test_sav_bytes, "application/octet-stream")},
        data={"spec": spec},
    )
    assert resp.status_code == 200
    wb = load_workbook(io.BytesIO(resp.content))

    # Summary should mention both banners
    ws_sum = wb["Summary"]
    banners_cell = None
    for row in ws_sum.iter_rows(min_col=1, max_col=2, max_row=15):
        if row[0].value == "Banners":
            banners_cell = row[1].value
            break
    assert banners_cell is not None
    assert "gender" in banners_cell
    assert "age_group" in banners_cell

    # Data sheet should have columns for both banners (2 gender + 3 age = 5 + Total = 6 data cols)
    ws = wb["satisfaction"]
    # Check letters row — should have A,B (gender) + C,D,E (age_group)
    letters = []
    for col in range(2, 10):
        val = ws.cell(row=5, column=col).value  # Letters row (row 5 with banner group header)
        if val and len(str(val)) <= 2 and str(val).isalpha():
            letters.append(str(val))
    assert len(letters) >= 5, f"Expected 5+ column letters, got {letters}"
    assert "A" in letters and "E" in letters


def test_tabulate_mrs(client, auth_headers, test_sav_bytes_with_mrs):
    """T1-3: MRS groups as crosstab rows."""
    spec = json.dumps({
        "banner": "gender",
        "stubs": [],
        "mrs_groups": {"Brand Awareness": ["AWARE_A", "AWARE_B", "AWARE_C"]},
    })
    resp = client.post(
        "/v1/tabulate",
        headers=auth_headers,
        files={"file": ("test_mrs.sav", test_sav_bytes_with_mrs, "application/octet-stream")},
        data={"spec": spec},
    )
    assert resp.status_code == 200
    assert int(resp.headers["X-Stubs-Success"]) >= 1
    wb = load_workbook(io.BytesIO(resp.content))
    assert "Brand Awareness" in wb.sheetnames


def test_tabulate_missing_banner(client, auth_headers, test_sav_bytes):
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
    spec = json.dumps({"banner": "gender", "stubs": ["Q999"]})
    resp = client.post(
        "/v1/tabulate",
        headers=auth_headers,
        files={"file": ("test.sav", test_sav_bytes, "application/octet-stream")},
        data={"spec": spec},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "VARIABLE_NOT_FOUND"
