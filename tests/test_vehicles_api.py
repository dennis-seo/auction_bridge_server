"""GET /api/v1/vehicles + /api/v1/vehicles/stats — mock 모드 회귀 테스트."""
from __future__ import annotations

import os

os.environ.setdefault("USE_MOCK", "true")

from fastapi.testclient import TestClient  # noqa: E402

from main import app  # noqa: E402

client = TestClient(app)


def test_list_basic_pagination():
    res = client.get("/api/v1/vehicles?limit=3")
    assert res.status_code == 200
    body = res.json()
    assert set(body.keys()) >= {"items", "total", "offset", "limit"}
    assert body["offset"] == 0
    assert body["limit"] == 3
    assert len(body["items"]) <= 3
    assert body["total"] >= len(body["items"])
    # 각 아이템에 차량 특화 필드가 있어야 함
    for item in body["items"]:
        assert "vehicle_category" in item
        assert "maker" in item


def test_filter_by_category():
    res = client.get("/api/v1/vehicles?vehicle_category=sedan&limit=50")
    assert res.status_code == 200
    items = res.json()["items"]
    assert len(items) > 0
    for item in items:
        assert item["vehicle_category"] == "sedan"


def test_filter_by_maker_partial():
    res = client.get("/api/v1/vehicles?maker=현대&limit=50")
    assert res.status_code == 200
    items = res.json()["items"]
    assert len(items) > 0
    for item in items:
        assert "현대" in (item["maker"] or "")


def test_filter_by_year_range():
    res = client.get("/api/v1/vehicles?year_model_min=2020&year_model_max=2024&limit=50")
    assert res.status_code == 200
    items = res.json()["items"]
    assert len(items) > 0
    for item in items:
        year = item["year_model"]
        assert year is not None and "2020" <= year <= "2024"


def test_filter_by_mileage_max():
    res = client.get("/api/v1/vehicles?mileage_km_max=50000&limit=50")
    assert res.status_code == 200
    items = res.json()["items"]
    assert len(items) > 0
    for item in items:
        assert item["mileage_km"] is not None and item["mileage_km"] <= 50000


def test_pagination_no_overlap():
    page1 = client.get("/api/v1/vehicles?offset=0&limit=2").json()
    page2 = client.get("/api/v1/vehicles?offset=2&limit=2").json()
    ids1 = {it["id"] for it in page1["items"]}
    ids2 = {it["id"] for it in page2["items"]}
    assert ids1.isdisjoint(ids2)


def test_stats_structure():
    res = client.get("/api/v1/vehicles/stats")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] > 0
    assert isinstance(body["by_category"], list) and len(body["by_category"]) > 0
    assert isinstance(body["by_fuel"], list) and len(body["by_fuel"]) > 0
    assert isinstance(body["by_transmission"], list) and len(body["by_transmission"]) > 0
    assert isinstance(body["by_maker_top"], list) and len(body["by_maker_top"]) > 0
    assert isinstance(body["by_year_model"], list) and len(body["by_year_model"]) > 0
    # category facet에는 한글 라벨이 함께 있어야 함
    assert any(c.get("label") for c in body["by_category"])


def test_invalid_year_pattern():
    res = client.get("/api/v1/vehicles?year_model_min=20a4")
    assert res.status_code == 422


def test_invalid_mileage_negative():
    res = client.get("/api/v1/vehicles?mileage_km_min=-1")
    assert res.status_code == 422
