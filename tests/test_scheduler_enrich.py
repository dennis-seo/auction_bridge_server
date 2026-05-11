"""enrich_bid_results_by_list + enrich_movable_image_urls 단위 테스트.

OnbidClient는 모킹하고, repo는 in-memory 가짜로 lookup_active_auction_ids /
upsert_bid_result / list_movable_missing_images / update_image_urls 만 검증한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from app.infrastructure.external.onbid_client import (
    CLTR_TYPE_CD,
    OnbidAssetService,
    OnbidPage,
)
from app.services.onbid_ingest_service import (
    BidResultPayload,
    EnrichStats,
    OnbidIngestService,
)


# ---- 가짜 OnbidClient ----
@dataclass
class _FakeClient:
    list_pages: dict[tuple[str, int], OnbidPage] = field(default_factory=dict)
    movable_details: dict[tuple[str, int], dict[str, Any]] = field(default_factory=dict)
    realty_details: dict[tuple[str, int], dict[str, Any]] = field(default_factory=dict)
    bid_infos: dict[tuple[str, int], dict[str, Any]] = field(default_factory=dict)
    list_calls: list[tuple[str, int]] = field(default_factory=list)
    detail_calls: list[tuple[str, int]] = field(default_factory=list)
    bid_info_calls: list[tuple[str, int]] = field(default_factory=list)

    async def list_bid_results(
        self, *, cltr_type_cd, prpt_div_cd, opbd_dt_start, opbd_dt_end,
        page_no, num_of_rows,
    ):
        self.list_calls.append((cltr_type_cd, page_no))
        return self.list_pages.get(
            (cltr_type_cd, page_no),
            OnbidPage(items=[], total_count=0, page_no=page_no, num_of_rows=num_of_rows),
        )

    async def get_movable_detail(self, *, cltr_mng_no, pbct_cdtn_no):
        self.detail_calls.append((cltr_mng_no, int(pbct_cdtn_no)))
        return self.movable_details.get((cltr_mng_no, int(pbct_cdtn_no)), {})

    async def get_realty_detail(self, *, cltr_mng_no, pbct_cdtn_no):
        return self.realty_details.get((cltr_mng_no, int(pbct_cdtn_no)), {})

    async def get_bid_info(self, *, cltr_mng_no, pbct_cdtn_no):
        self.bid_info_calls.append((cltr_mng_no, int(pbct_cdtn_no)))
        return self.bid_infos.get((cltr_mng_no, int(pbct_cdtn_no)), {})


# ---- 가짜 Repo ----
@dataclass
class _FakeRepo:
    active_map: dict[tuple[str, int], int] = field(default_factory=dict)
    missing_realty: list[tuple[int, str, int]] = field(default_factory=list)
    missing_movable: list[tuple[int, str, int]] = field(default_factory=list)
    missing_bid_info: list[tuple[int, str, int]] = field(default_factory=list)
    upserts: list[tuple[int, BidResultPayload]] = field(default_factory=list)
    image_updates: dict[int, list[str]] = field(default_factory=dict)
    bid_info_updates: dict[int, dict[str, Any]] = field(default_factory=dict)

    async def lookup_active_auction_ids(self, keys):
        return {k: aid for k, aid in self.active_map.items() if k in set(keys)}

    async def upsert_bid_result(self, auction_id, payload):
        self.upserts.append((auction_id, payload))

    async def list_realty_missing_images(self, limit):
        return self.missing_realty[:limit]

    async def list_movable_missing_images(self, limit):
        return self.missing_movable[:limit]

    async def list_auctions_missing_bid_info(self, limit):
        return self.missing_bid_info[:limit]

    async def update_image_urls(self, auction_id, urls):
        self.image_updates[auction_id] = list(urls)

    async def update_bid_info(self, auction_id, bid_info):
        self.bid_info_updates[auction_id] = dict(bid_info)


def _onbid_item(cltr: str, pbct: int, status_cd: str = "0011") -> dict[str, Any]:
    return {
        "cltrMngNo": cltr,
        "pbctCdtnNo": pbct,
        "pbctStatCd": status_cd,
        "pbctStatNm": "유찰",
        "scfbAmt": "",
        "bidAmtClgCont": "",
    }


@pytest.mark.asyncio
async def test_enrich_bid_results_by_list_only_matched_active():
    """list로 받은 결과 중 active(ongoing/scheduled) 매물에만 upsert가 일어나야 함."""
    fake_client = _FakeClient()
    # 부동산 페이지 1건: 1개는 active 매칭, 1개는 매칭 안 됨
    realty_cd = CLTR_TYPE_CD[OnbidAssetService.REALTY]
    fake_client.list_pages[(realty_cd, 1)] = OnbidPage(
        items=[_onbid_item("R-1", 100), _onbid_item("R-NOMATCH", 999)],
        total_count=2, page_no=1, num_of_rows=100,
    )
    fake_repo = _FakeRepo(active_map={("R-1", 100): 11})

    svc = OnbidIngestService(client=fake_client, geocoder=None, repo=fake_repo)  # type: ignore[arg-type]
    stats = await svc.enrich_bid_results_by_list(days_lookback=1, max_pages_per_combo=1)

    assert stats.api_calls >= 1
    assert stats.enriched == 1
    assert len(fake_repo.upserts) == 1
    assert fake_repo.upserts[0][0] == 11
    assert fake_repo.upserts[0][1].cltr_mng_no == "R-1"


@pytest.mark.asyncio
async def test_enrich_movable_image_urls_writes_when_potoUrlList_present():
    fake_client = _FakeClient()
    fake_client.movable_details[("M-1", 200)] = {
        "potoUrlList": [{"urlAdr": "http://example.com/a.jpg"}, {"urlAdr": "http://example.com/b.jpg"}],
    }
    fake_client.movable_details[("M-2", 201)] = {"potoUrlList": None}  # 빈 응답

    fake_repo = _FakeRepo(missing_movable=[(21, "M-1", 200), (22, "M-2", 201)])
    svc = OnbidIngestService(client=fake_client, geocoder=None, repo=fake_repo)  # type: ignore[arg-type]

    stats = await svc.enrich_movable_image_urls(limit=10)
    assert isinstance(stats, EnrichStats)
    assert stats.targeted == 2
    assert stats.api_calls == 2
    assert stats.enriched == 1
    assert fake_repo.image_updates == {
        21: ["http://example.com/a.jpg", "http://example.com/b.jpg"]
    }


@pytest.mark.asyncio
async def test_enrich_bid_info_stores_normalized_dict():
    fake_client = _FakeClient()
    fake_client.bid_infos[("X-1", 300)] = {
        "cltrMngNo": "X-1",
        "pbctCdtnNo": 300,
        "collbBidPsblYn": "Y",
        "subtBidPsblYn": "N",
        "pbctTdpsCont": "최저입찰가*5%",
        "ptctCmsn": "10000",
        "usbdNft": 2,
        "pbancMngNo": "PB-2025-001",
        "onbidPbancNm": "2025년 1차 공고",
        "prcnBidClgList": [
            {
                "pbctNsq": "1", "pbctsn": "1",
                "cltrOpbdDt": "202501201400",
                "pbctStatNm": "유찰",
                "scfbAmt": "0",
            }
        ],
        "cseqBidInfClgList": [
            {
                "bidMngNo": "B-001",
                "bidDivNm": "인터넷",
                "cltrBidBgngDt": "202502100900",
                "cltrBidEndDt": "202502151800",
            }
        ],
    }
    fake_client.bid_infos[("X-2", 301)] = {}  # 빈 응답 → enriched 카운트 제외

    fake_repo = _FakeRepo(
        missing_bid_info=[(31, "X-1", 300), (32, "X-2", 301)],
    )
    svc = OnbidIngestService(client=fake_client, geocoder=None, repo=fake_repo)  # type: ignore[arg-type]

    stats = await svc.enrich_bid_info(limit=10)
    assert stats.targeted == 2
    assert stats.api_calls == 2
    assert stats.enriched == 1
    assert stats.failed == 1
    assert 31 in fake_repo.bid_info_updates
    assert 32 not in fake_repo.bid_info_updates

    saved = fake_repo.bid_info_updates[31]
    # 정규화된 6개 묶음이 모두 존재
    assert set(saved.keys()) >= {
        "methods", "terms", "restrictions", "announcement",
        "previous_rounds", "round_schedules", "raw",
    }
    assert saved["methods"]["collab_bid"] is True
    assert saved["methods"]["proxy_bid"] is False
    assert saved["terms"]["deposit_text"] == "최저입찰가*5%"
    assert saved["terms"]["participation_fee"] == 10000
    assert saved["terms"]["failed_count_cumulative"] == 2
    assert saved["announcement"]["pbanc_mng_no"] == "PB-2025-001"
    assert len(saved["previous_rounds"]) == 1
    assert saved["previous_rounds"][0]["result_name"] == "유찰"
    assert len(saved["round_schedules"]) == 1
    assert saved["round_schedules"][0]["bid_div"] == "인터넷"
    # raw는 원본 dict 보존
    assert saved["raw"]["cltrMngNo"] == "X-1"
