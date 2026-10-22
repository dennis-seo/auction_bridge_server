"""GET /api/v1/auctions (지도 bbox) — mock 모드 회귀 테스트."""
from __future__ import annotations

import os

os.environ.setdefault("USE_MOCK", "true")

from fastapi.testclient import TestClient  # noqa: E402

from main import app  # noqa: E402

client = TestClient(app)

_KOREA_BBOX = "min_lng=124&max_lng=132&min_lat=33&max_lat=39"


def test_status_omitted_excludes_ended():
    res = client.get(f"/api/v1/auctions?{_KOREA_BBOX}&limit=500")
    assert res.status_code == 200
    items = res.json()["items"]
    assert len(items) > 0
    for item in items:
        assert item["status"] in ("scheduled", "ongoing")


def test_explicit_status_returns_ended():
    res = client.get(f"/api/v1/auctions?{_KOREA_BBOX}&status=sold&limit=500")
    assert res.status_code == 200
    items = res.json()["items"]
    assert [item["id"] for item in items] == [1121]
