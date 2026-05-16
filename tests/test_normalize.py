"""normalize_realty / normalize_movable / normalize_vehicle / normalize_bid_result."""
from __future__ import annotations

from datetime import timedelta, timezone

from app.domain.auction.schemas import (
    AssetType,
    AuctionSource,
    AuctionStatus,
    PropertyCategory,
    VehicleCategory,
)
from app.services.onbid_ingest_service import (
    _split_amounts,
    normalize_bid_result,
    normalize_movable,
    normalize_realty,
    normalize_vehicle,
)
from tests.fixtures.onbid_samples import (
    BID_RESULT_FAILED,
    BID_RESULT_SOLD,
    MOVABLE_DEVICE,
    REALTY_LAND,
    REALTY_NEUNGSAENGHWAL,
    VEHICLE_PATROL,
)

KST = timezone(timedelta(hours=9))


class TestNormalizeRealty:
    def test_neungsaenghwal_commercial(self):
        item = normalize_realty(REALTY_NEUNGSAENGHWAL)
        assert item is not None
        assert item.source == AuctionSource.ONBID
        assert item.asset_type == AssetType.REALTY
        assert item.cltr_mng_no == "2022-0100-002855"
        assert item.pbct_cdtn_no == 3912726
        assert item.title == "경기도 평택시 장당동 483-6 201호 근린생활시설"
        # parcel level: title의 지번 (483-6)이 행정주소에 결합됨
        assert item.address == "경기도 평택시 장당동 483-6"
        assert item.region_sido == "경기도"
        assert item.region_sigungu == "평택시"
        assert item.region_emd == "장당동"
        assert item.appraisal_price == 256000000
        assert item.min_bid_price == 373248000
        assert item.min_bid_price_text == "373248000"
        # 2999 sentinel 처리
        assert item.bid_begin_at is None
        assert item.bid_end_at is None
        assert item.failed_count == 1
        assert item.pvct_trgt_yn is False
        assert item.batc_bid_yn is False
        # realty attrs
        assert item.realty is not None
        assert item.realty.property_category == PropertyCategory.COMMERCIAL
        assert item.realty.land_sqms == 62.453
        assert item.realty.bld_sqms == 94.113
        assert item.realty.alc_yn is False
        # 다른 카테고리는 None
        assert item.vehicle is None
        assert item.movable is None

    def test_land(self):
        item = normalize_realty(REALTY_LAND)
        assert item is not None
        assert item.realty.property_category == PropertyCategory.LAND
        # 정상 날짜는 정상 파싱
        assert item.bid_begin_at is not None
        assert item.bid_begin_at.year == 2026
        assert item.bid_begin_at.month == 7

    def test_missing_required_returns_none(self):
        # cltrMngNo 누락 → None (skip)
        bad = dict(REALTY_LAND)
        bad["cltrMngNo"] = ""
        assert normalize_realty(bad) is None

    def test_missing_pbct_cdtn_no_returns_none(self):
        bad = dict(REALTY_LAND)
        bad["pbctCdtnNo"] = None
        assert normalize_realty(bad) is None


class TestNormalizeVehicle:
    def test_patrol_car(self):
        item = normalize_vehicle(VEHICLE_PATROL)
        assert item is not None
        assert item.asset_type == AssetType.VEHICLE
        assert item.title == "순찰차205거4156"
        assert item.address == "강원특별자치도 춘천시 신동면"
        # 비공개 — text는 보존, int는 None
        assert item.min_bid_price is None
        assert item.min_bid_price_text == "비공개"
        # vehicle attrs
        assert item.vehicle is not None
        assert item.vehicle.vehicle_category == VehicleCategory.SEDAN  # usg_scls=승용차
        assert item.vehicle.maker == "현대"
        assert item.vehicle.model_name == "쏘나타"  # str_or_none이 leading space 제거
        assert item.vehicle.year_model == "2020"
        assert item.vehicle.plate_no == "205거4156"
        assert item.vehicle.mileage_km == 204661
        assert item.vehicle.displacement_cc == 1999
        assert item.vehicle.fuel == "휘발유"
        assert item.vehicle.color == "흰색"
        assert item.realty is None


class TestNormalizeMovable:
    def test_device(self):
        item = normalize_movable(MOVABLE_DEVICE)
        assert item is not None
        assert item.asset_type == AssetType.MOVABLE
        # 입찰마감(0003)은 ongoing 매핑
        assert item.status == AuctionStatus.ONGOING
        assert item.movable is not None
        assert item.movable.maker == "션경산업"
        assert item.movable.model_name == "SK-UV055"
        assert item.movable.manufacture_year == "2018"
        assert item.movable.size_text == "1000*1350*430"
        assert item.movable.weight_text == "85kg"
        assert item.movable.custody_place == "OO창고"
        assert item.movable.commodity_name == "주방기구소독기"
        assert item.realty is None
        assert item.vehicle is None


class TestSplitAmounts:
    def test_single(self):
        assert _split_amounts("279100000") == [279100000]

    def test_multi_pipe(self):
        assert _split_amounts("279100000|265000000|240500000") == [
            279100000, 265000000, 240500000,
        ]

    def test_empty(self):
        assert _split_amounts("") == []
        assert _split_amounts(None) == []

    def test_with_invalid_token(self):
        # 한 토큰이 invalid면 그것만 빠지고 나머지는 정상
        assert _split_amounts("100|abc|200") == [100, 200]


class TestNormalizeBidResult:
    def test_sold(self):
        p = normalize_bid_result(BID_RESULT_SOLD)
        assert p is not None
        assert p.status == AuctionStatus.SOLD
        assert p.winning_bid_amount == 279100000
        assert p.winning_bid_amounts == [279100000]
        assert p.bid_amounts == [
            279100000, 265000000, 240500000, 200100000, 150000000, 100000000,
        ]
        assert p.valid_bidder_count == 6
        assert p.invalid_bidder_count == 0
        assert p.opbd_at is not None
        assert p.opbd_at.year == 2026 and p.opbd_at.month == 5
        assert p.apsl_scfb_ratio == 197.78
        assert p.announce_name == "2026년 국유임산물(주벌 입목처분_유포)"

    def test_failed(self):
        p = normalize_bid_result(BID_RESULT_FAILED)
        assert p is not None
        assert p.status == AuctionStatus.FAILED
        assert p.winning_bid_amount is None
        assert p.winning_bid_amounts == []
        assert p.valid_bidder_count == 0
        assert p.rtrcn_reason == "유효한 입찰자 없음"

    def test_missing_required_returns_none(self):
        bad = dict(BID_RESULT_FAILED)
        bad["cltrMngNo"] = ""
        assert normalize_bid_result(bad) is None
