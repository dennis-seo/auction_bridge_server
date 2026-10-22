"""GET /api/v1/auctions/{id} — 상세 응답 rounds/식별 필드 mock 모드 회귀 테스트."""
from __future__ import annotations

import os

os.environ.setdefault("USE_MOCK", "true")

from fastapi.testclient import TestClient  # noqa: E402

from main import app  # noqa: E402

client = TestClient(app)


def test_detail_contains_rounds():
    res = client.get("/api/v1/auctions/1001")
    assert res.status_code == 200
    body = res.json()
    assert "rounds" in body
    rounds = body["rounds"]
    assert len(rounds) >= 2
    for r in rounds:
        assert {"auction_id", "round_label", "status", "is_current"} <= set(r.keys())
    # 현재 회차가 정확히 1건 표시
    assert sum(1 for r in rounds if r["is_current"]) == 1


def test_rounds_result_shape():
    res = client.get("/api/v1/auctions/1001")
    body = res.json()
    finished = [r for r in body["rounds"] if r["result"] is not None]
    assert len(finished) >= 1
    for r in finished:
        assert {"winning_bid_amount", "apsl_scfb_ratio",
                "valid_bidder_count", "opbd_at"} <= set(r["result"].keys())


def test_detail_code_names_prpt_div():
    res = client.get("/api/v1/auctions/1001")
    body = res.json()
    assert "code_names" in body
    assert "prpt_div" in body["code_names"]


def test_detail_not_found():
    res = client.get("/api/v1/auctions/999999")
    assert res.status_code == 404
