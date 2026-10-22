"""GET /api/v1/realty — mock 모드 회귀 테스트."""
from __future__ import annotations

import os

os.environ.setdefault("USE_MOCK", "true")

from fastapi.testclient import TestClient  # noqa: E402

from main import app  # noqa: E402

client = TestClient(app)


def test_list_basic_pagination():
    res = client.get("/api/v1/realty?limit=3")
    assert res.status_code == 200
    body = res.json()
    assert set(body.keys()) >= {"items", "total", "offset", "limit"}
    assert body["offset"] == 0
    assert body["limit"] == 3
    assert len(body["items"]) <= 3
    assert body["total"] >= len(body["items"])
    for item in body["items"]:
        assert "property_category" in item
        assert "cltr_mng_no" in item
        assert "prpt_div_nm" in item


def test_filter_by_category_multi():
    res = client.get(
        "/api/v1/realty?property_category=apartment&property_category=officetel&limit=50"
    )
    assert res.status_code == 200
    items = res.json()["items"]
    assert len(items) > 0
    for item in items:
        assert item["property_category"] in ("apartment", "officetel")


def test_filter_by_region():
    res = client.get("/api/v1/realty?region_sido=서울특별시&limit=50")
    assert res.status_code == 200
    items = res.json()["items"]
    assert len(items) > 0
    for item in items:
        assert item["region_sido"] == "서울특별시"


def test_filter_by_price_range_excludes_undisclosed():
    res = client.get("/api/v1/realty?min_bid_price_min=1&limit=50")
    assert res.status_code == 200
    items = res.json()["items"]
    assert len(items) > 0
    # 가격 범위 필터 시 min_bid_price가 비공개(None)인 물건은 제외
    for item in items:
        assert item["min_bid_price"] is not None


def test_filter_by_failed_count():
    res = client.get("/api/v1/realty?failed_count_min=1&limit=50")
    assert res.status_code == 200
    items = res.json()["items"]
    assert len(items) > 0
    for item in items:
        assert item["failed_count"] >= 1


def test_sort_price_asc():
    res = client.get("/api/v1/realty?sort=price_asc&min_bid_price_min=1&limit=50")
    assert res.status_code == 200
    prices = [it["min_bid_price"] for it in res.json()["items"]]
    assert prices == sorted(prices)


def test_sort_failed_count_desc():
    res = client.get("/api/v1/realty?sort=failed_count&limit=50")
    assert res.status_code == 200
    counts = [it["failed_count"] for it in res.json()["items"]]
    assert counts == sorted(counts, reverse=True)


def test_status_alias_filter():
    res = client.get("/api/v1/realty?status=sold&limit=50")
    assert res.status_code == 200
    items = res.json()["items"]
    assert len(items) > 0
    for item in items:
        assert item["status"] == "sold"


def test_pagination_no_overlap():
    page1 = client.get("/api/v1/realty?offset=0&limit=2").json()
    page2 = client.get("/api/v1/realty?offset=2&limit=2").json()
    ids1 = {it["id"] for it in page1["items"]}
    ids2 = {it["id"] for it in page2["items"]}
    assert ids1.isdisjoint(ids2)


def test_invalid_sort_rejected():
    res = client.get("/api/v1/realty?sort=nope")
    assert res.status_code == 422


def test_invalid_negative_price():
    res = client.get("/api/v1/realty?appraisal_price_min=-1")
    assert res.status_code == 422
