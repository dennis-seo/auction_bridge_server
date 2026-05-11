"""enrich_bid_results_by_list + enrich_movable_image_urls 단위 테스트.

OnbidClient는 모킹하고, repo는 in-memory 가짜로 lookup_active_auction_ids /
upsert_bid_result / list_movable_missing_images / update_image_urls 만 검증한다.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from typing import Any

import pytest

from app.domain.auction.repository import (
    AuctionSiblingMeta,
    PbancEnrichGroup,
    PbancResolveTarget,
)
from app.domain.auction.schemas import (
    AssetType,
    AuctionUpsertItem,
    PropertyCategory,
)
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


_KST = timezone(timedelta(hours=9))


# ---- 가짜 OnbidClient ----
@dataclass
class _FakeClient:
    list_pages: dict[tuple[str, int], OnbidPage] = field(default_factory=dict)
    movable_details: dict[tuple[str, int], dict[str, Any]] = field(default_factory=dict)
    realty_details: dict[tuple[str, int], dict[str, Any]] = field(default_factory=dict)
    bid_infos: dict[tuple[str, int], dict[str, Any]] = field(default_factory=dict)
    # D안 — 공고 API 응답
    announcement_pages: dict[tuple[str, str, int], OnbidPage] = field(default_factory=dict)
    announcement_cltrs: dict[str, OnbidPage] = field(default_factory=dict)
    list_calls: list[tuple[str, int]] = field(default_factory=list)
    detail_calls: list[tuple[str, int]] = field(default_factory=list)
    bid_info_calls: list[tuple[str, int]] = field(default_factory=list)
    announcement_list_calls: list[tuple[str, str, int]] = field(default_factory=list)
    announcement_cltrs_calls: list[str] = field(default_factory=list)

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

    async def list_announcements(
        self, *, cltr_type_cd, prpt_div_cd=None,
        bid_prd_ymd_start=None, bid_prd_ymd_end=None,
        opbd_dt_start=None, opbd_dt_end=None,
        page_no=1, num_of_rows=500,
    ):
        ymd = bid_prd_ymd_start or opbd_dt_start or ""
        key = (cltr_type_cd, ymd, page_no)
        self.announcement_list_calls.append(key)
        return self.announcement_pages.get(
            key,
            OnbidPage(items=[], total_count=0, page_no=page_no, num_of_rows=num_of_rows),
        )

    async def get_announcement_cltrs(
        self, *, pbanc_mng_no, page_no=1, num_of_rows=500,
    ):
        self.announcement_cltrs_calls.append(pbanc_mng_no)
        return self.announcement_cltrs.get(
            pbanc_mng_no,
            OnbidPage(items=[], total_count=0, page_no=page_no, num_of_rows=num_of_rows),
        )


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
    # D안 enrich
    missing_pbanc_mng_no: list[PbancResolveTarget] = field(default_factory=list)
    pbanc_groups: list[PbancEnrichGroup] = field(default_factory=list)
    pbanc_mng_no_updates: list[tuple[int, str]] = field(default_factory=list)
    upsert_many_calls: list[list[AuctionUpsertItem]] = field(default_factory=list)

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

    async def list_auctions_missing_pbanc_mng_no(self, limit):
        return self.missing_pbanc_mng_no[:limit]

    async def update_pbanc_mng_no_batch(self, mapping):
        self.pbanc_mng_no_updates.extend(mapping)
        return len(mapping)

    async def list_pbanc_groups_for_round_enrich(self, limit):
        return self.pbanc_groups[:limit]

    async def upsert_many(self, items):
        self.upsert_many_calls.append(list(items))
        # 전체 신규 가정 (테스트 단순화)
        return (len(items), 0)


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


# =====================================================================
# D안 — 공고 API 체인 enrich 테스트
# =====================================================================
def _sibling(
    asset_type: AssetType = AssetType.REALTY,
    *, lat: float = 37.43, lng: float = 127.14,
    region_sido: str = "경기도", region_sigungu: str = "성남시 중원구",
    region_emd: str = "하대원동",
    property_category: PropertyCategory | None = PropertyCategory.APARTMENT,
) -> AuctionSiblingMeta:
    return AuctionSiblingMeta(
        asset_type=asset_type,
        region_sido=region_sido,
        region_sigungu=region_sigungu,
        region_emd=region_emd,
        address=f"{region_sido} {region_sigungu} {region_emd}",
        lat=lat, lng=lng,
        ltno_pnu="4113310900001470005",
        rdnm_pnu="4113331790080200013300000",
        request_org_nm=None,
        announce_org_nm="케이비부동산신탁",
        thumbnail_url="https://example.com/t.jpg",
        property_category=property_category,
    )


@pytest.mark.asyncio
async def test_enrich_pbanc_mng_no_resolves_via_bidPrdYmd():
    """getPbancList2 응답에서 onbid_pbanc_no 매칭으로 pbanc_mng_no를 찾아 업데이트한다."""
    fake_client = _FakeClient()
    realty_cd = CLTR_TYPE_CD[OnbidAssetService.REALTY]
    # 검색 키 = bidPrdYmd 20260518, asset=realty
    fake_client.announcement_pages[(realty_cd, "20260518", 1)] = OnbidPage(
        items=[
            {"onbidPbancNo": 885521, "pbancMngNo": "202605-11881-00"},
            {"onbidPbancNo": 999999, "pbancMngNo": "202605-99999-00"},  # 무관
        ],
        total_count=2, page_no=1, num_of_rows=500,
    )

    bid_begin = datetime(2026, 5, 18, 13, 0, tzinfo=_KST)
    fake_repo = _FakeRepo(
        missing_pbanc_mng_no=[
            PbancResolveTarget(
                auction_id=1001, onbid_pbanc_no=885521,
                asset_type=AssetType.REALTY, bid_begin_at=bid_begin,
            ),
        ],
    )
    svc = OnbidIngestService(client=fake_client, geocoder=None, repo=fake_repo)  # type: ignore[arg-type]

    stats = await svc.enrich_pbanc_mng_no(limit=50)
    assert stats.targeted == 1
    assert stats.enriched == 1
    assert stats.failed == 0
    assert fake_repo.pbanc_mng_no_updates == [(1001, "202605-11881-00")]
    # bidPrdYmd 검색조건이 정확히 전달됐는지
    assert (realty_cd, "20260518", 1) in fake_client.announcement_list_calls


@pytest.mark.asyncio
async def test_enrich_pbanc_mng_no_marks_failed_when_no_match():
    """getPbancList2 응답에 onbid_pbanc_no 매칭이 없으면 failed += 1."""
    fake_client = _FakeClient()
    realty_cd = CLTR_TYPE_CD[OnbidAssetService.REALTY]
    fake_client.announcement_pages[(realty_cd, "20260518", 1)] = OnbidPage(
        items=[{"onbidPbancNo": 111111, "pbancMngNo": "X"}],  # 매칭 안 됨
        total_count=1, page_no=1, num_of_rows=500,
    )
    fake_repo = _FakeRepo(
        missing_pbanc_mng_no=[
            PbancResolveTarget(
                auction_id=1001, onbid_pbanc_no=885521,
                asset_type=AssetType.REALTY,
                bid_begin_at=datetime(2026, 5, 18, 13, 0, tzinfo=_KST),
            ),
        ],
    )
    svc = OnbidIngestService(client=fake_client, geocoder=None, repo=fake_repo)  # type: ignore[arg-type]

    stats = await svc.enrich_pbanc_mng_no(limit=50)
    assert stats.failed == 1
    assert stats.enriched == 0
    assert fake_repo.pbanc_mng_no_updates == []


@pytest.mark.asyncio
async def test_enrich_missing_rounds_skips_existing_keys():
    """get_announcement_cltrs 응답 중 이미 보유한 (cltr, pbct)는 upsert 후보에서 제외."""
    fake_client = _FakeClient()
    fake_client.announcement_cltrs["PMN-001"] = OnbidPage(
        items=[
            # 회차 1차 — 신규
            {"cltrMngNo": "C-1", "pbctCdtnNo": 1001, "pbctNsq": "1",
             "pbctStatCd": "0001", "pbctStatNm": "입찰준비중",
             "cltrBidBgngDt": "202605181300", "cltrBidEndDt": "202605182330",
             "apslEvlAmt": "890000000", "lowstBidPrcIndctCont": "890000000",
             "usbdNft": 10, "feeRate": "100"},
            # 회차 2차 — 이미 보유 → skip
            {"cltrMngNo": "C-1", "pbctCdtnNo": 1002, "pbctNsq": "2",
             "pbctStatCd": "0001", "pbctStatNm": "입찰준비중"},
        ],
        total_count=2, page_no=1, num_of_rows=500,
    )

    group = PbancEnrichGroup(
        pbanc_mng_no="PMN-001",
        existing_keys={("C-1", 1002)},  # 회차 2차만 보유
        siblings={"C-1": _sibling()},
    )
    fake_repo = _FakeRepo(pbanc_groups=[group])
    svc = OnbidIngestService(client=fake_client, geocoder=None, repo=fake_repo)  # type: ignore[arg-type]

    stats = await svc.enrich_missing_rounds_via_pbanc(limit=10)
    assert stats.targeted == 1   # 그룹 수
    assert stats.api_calls == 1
    assert stats.enriched == 1   # 신규 row 1개 (회차 1차만)

    assert len(fake_repo.upsert_many_calls) == 1
    upserted = fake_repo.upsert_many_calls[0]
    assert len(upserted) == 1
    item = upserted[0]
    assert item.cltr_mng_no == "C-1"
    assert item.pbct_cdtn_no == 1001  # 회차 1차


@pytest.mark.asyncio
async def test_enrich_missing_rounds_inherits_sibling_meta():
    """신규 회차 row에 sibling의 region/lat/lng/PNU/property_category가 들어가야 함."""
    fake_client = _FakeClient()
    fake_client.announcement_cltrs["PMN-002"] = OnbidPage(
        items=[
            {"cltrMngNo": "C-9", "pbctCdtnNo": 5962798, "pbctNsq": "1",
             "pbctStatCd": "0001", "pbctStatNm": "입찰준비중",
             "cltrBidBgngDt": "202605181300", "cltrBidEndDt": "202605182330",
             "apslEvlAmt": "870000000", "lowstBidPrcIndctCont": "870000000",
             "usbdNft": 10, "onbidPbancNo": "885521", "feeRate": "100",
             "onbidCltrNm": "경기도 성남시 중원구 하대원동 ... 801호 아파트"},
        ],
        total_count=1, page_no=1, num_of_rows=500,
    )

    sibling = _sibling(
        lat=37.427663, lng=127.144336,
        region_sigungu="성남시 중원구", region_emd="하대원동",
        property_category=PropertyCategory.APARTMENT,
    )
    group = PbancEnrichGroup(
        pbanc_mng_no="PMN-002",
        existing_keys=set(),
        siblings={"C-9": sibling},
    )
    fake_repo = _FakeRepo(pbanc_groups=[group])
    svc = OnbidIngestService(client=fake_client, geocoder=None, repo=fake_repo)  # type: ignore[arg-type]

    stats = await svc.enrich_missing_rounds_via_pbanc(limit=10)
    assert stats.enriched == 1
    item = fake_repo.upsert_many_calls[0][0]
    assert item.asset_type == AssetType.REALTY
    assert item.pbanc_mng_no == "PMN-002"
    # sibling 상속 검증
    assert item.region_sido == "경기도"
    assert item.region_sigungu == "성남시 중원구"
    assert item.region_emd == "하대원동"
    assert item.lat == 37.427663
    assert item.lng == 127.144336
    assert item.ltno_pnu == "4113310900001470005"
    assert item.thumbnail_url == "https://example.com/t.jpg"
    # 회차 정보는 API 응답에서 들어와야 함
    assert item.pbct_nsq == "1"
    assert item.appraisal_price == 870000000
    assert item.min_bid_price == 870000000
    assert item.failed_count == 10
    # realty attrs 채워짐
    assert item.realty is not None
    assert item.realty.property_category == PropertyCategory.APARTMENT
