"""응답 시각 KST(+09:00) 직렬화 회귀 테스트."""
from __future__ import annotations

import os
from datetime import datetime, timezone

os.environ.setdefault("USE_MOCK", "true")

from fastapi.testclient import TestClient  # noqa: E402

from app.domain.auction.schemas import (  # noqa: E402
    AssetType,
    AuctionListItem,
    AuctionSource,
    AuctionStatus,
)
from main import app  # noqa: E402

client = TestClient(app)


def _item(bid_end_at: datetime) -> AuctionListItem:
    return AuctionListItem(
        id=1, source=AuctionSource.ONBID, asset_type=AssetType.REALTY,
        status=AuctionStatus.ONGOING, bid_end_at=bid_end_at,
    )


def test_utc_converted_to_kst():
    # asyncpg가 돌려주는 UTC 08:00 = 한국 17:00 마감
    dumped = _item(datetime(2026, 5, 20, 8, 0, tzinfo=timezone.utc)).model_dump(mode="json")
    assert dumped["bid_end_at"] == "2026-05-20T17:00:00+09:00"


def test_naive_treated_as_utc():
    dumped = _item(datetime(2026, 5, 20, 8, 0)).model_dump(mode="json")
    assert dumped["bid_end_at"] == "2026-05-20T17:00:00+09:00"


def test_python_value_unchanged():
    # 직렬화 때만 바뀌고 모델 값(UTC)은 그대로
    dt = datetime(2026, 5, 20, 8, 0, tzinfo=timezone.utc)
    assert _item(dt).bid_end_at == dt


def test_api_responses_use_kst_offset():
    bbox = client.get(
        "/api/v1/auctions?min_lng=124&max_lng=132&min_lat=33&max_lat=39&limit=500"
    ).json()["items"]
    realty = client.get("/api/v1/realty?limit=100").json()["items"]
    values = [i["bid_end_at"] for i in bbox + realty if i.get("bid_end_at")]
    assert values
    for v in values:
        assert v.endswith("+09:00"), v
