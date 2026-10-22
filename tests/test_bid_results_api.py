"""GET /api/v1/bid-results — mock 모드 회귀 테스트."""
from __future__ import annotations

import os

os.environ.setdefault("USE_MOCK", "true")

from fastapi.testclient import TestClient  # noqa: E402

from main import app  # noqa: E402

client = TestClient(app)


def test_list_basic_pagination():
    res = client.get("/api/v1/bid-results?limit=2")
    assert res.status_code == 200
    body = res.json()
    assert set(body.keys()) >= {"items", "total", "offset", "limit"}
    assert len(body["items"]) <= 2
    for item in body["items"]:
        assert "result" in item
        assert "winning_bid_amount" in item
        assert "apsl_scfb_ratio" in item
        assert "opbd_at" in item


def test_default_sort_opbd_at_desc():
    res = client.get("/api/v1/bid-results?limit=50")
    assert res.status_code == 200
    dates = [it["opbd_at"] for it in res.json()["items"] if it["opbd_at"]]
    assert dates == sorted(dates, reverse=True)


def test_filter_result_sold():
    res = client.get("/api/v1/bid-results?result=sold&limit=50")
    assert res.status_code == 200
    items = res.json()["items"]
    assert len(items) > 0
    for item in items:
        assert item["result"] == "sold"
        assert item["winning_bid_amount"] is not None


def test_filter_asset_type():
    res = client.get("/api/v1/bid-results?asset_type=realty&limit=50")
    assert res.status_code == 200
    items = res.json()["items"]
    assert len(items) > 0
    for item in items:
        assert item["asset_type"] == "realty"


def test_filter_region():
    res = client.get("/api/v1/bid-results?region_sido=인천광역시&limit=50")
    assert res.status_code == 200
    items = res.json()["items"]
    assert len(items) > 0
    for item in items:
        assert item["region_sido"] == "인천광역시"


def test_sort_ratio_desc():
    res = client.get("/api/v1/bid-results?sort=ratio_desc&result=sold&limit=50")
    assert res.status_code == 200
    ratios = [it["apsl_scfb_ratio"] for it in res.json()["items"]]
    non_null = [r for r in ratios if r is not None]
    assert non_null == sorted(non_null, reverse=True)


def test_invalid_result_rejected():
    res = client.get("/api/v1/bid-results?result=nope")
    assert res.status_code == 422
