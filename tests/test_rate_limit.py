"""레이트리밋 회귀 테스트 — include_router로 붙인 /api/v1 라우트에도 한도가 걸려야 한다.

FastAPI가 included router를 래핑하는 버전에서는 slowapi가 핸들러를 못 찾아
/api/v1 전체가 한도 검사에서 조용히 빠졌다(/health만 적용).
"""
from __future__ import annotations

import os

os.environ.setdefault("USE_MOCK", "true")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import get_settings  # noqa: E402


@pytest.fixture
def limited_client(monkeypatch):
    monkeypatch.setenv("USE_MOCK", "true")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("RATE_LIMIT_DEFAULT", "3/minute")
    get_settings.cache_clear()
    from main import create_app

    yield TestClient(create_app())
    get_settings.cache_clear()


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/auctions/stats",
        "/api/v1/realty?limit=1",
        "/api/v1/bid-results?limit=1",
        "/api/v1/auctions?min_lng=124&max_lng=132&min_lat=33&max_lat=39",
    ],
)
def test_api_routes_are_rate_limited(limited_client, path):
    codes = [limited_client.get(path).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]


def test_health_is_rate_limited(limited_client):
    codes = [limited_client.get("/health").status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]
