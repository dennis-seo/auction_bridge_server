"""Mock 구현 — 차세대 v2 스키마 기준. USE_MOCK=true일 때 사용."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.domain.auction.repository import (
    AuctionRepository,
    PbancEnrichGroup,
    PbancResolveTarget,
)
from app.domain.auction.schemas import (
    ASSET_TYPE_LABELS_KO,
    PROPERTY_CATEGORY_LABELS_KO,
    VEHICLE_CATEGORY_LABELS_KO,
    AssetGroupStat,
    AssetType,
    AuctionDetail,
    AuctionListItem,
    AuctionSource,
    AuctionStatsResponse,
    AuctionStatus,
    AuctionUpsertItem,
    CategorySubStat,
    PropertyCategory,
    RealtyDetails,
    RightsAnalysisSummary,
    SourceStat,
    VehicleCategory,
    VehicleDetails,
    VehicleFacetCount,
    VehicleListItem,
    VehicleListQuery,
    VehicleMakerCount,
    VehicleStatsResponse,
    VehicleYearBucket,
)


_NOW = datetime.now(timezone.utc)

_MOCK_ITEMS: list[AuctionListItem] = [
    AuctionListItem(
        id=1001,
        source=AuctionSource.ONBID,
        asset_type=AssetType.REALTY,
        status=AuctionStatus.ONGOING,
        title="서울 중구 아파트 (mock)",
        address="서울특별시 중구 세종대로 110",
        region_sido="서울특별시",
        region_sigungu="중구",
        lat=37.5665, lng=126.9780,
        appraisal_price=1_100_000_000,
        min_bid_price=850_000_000,
        bid_end_at=_NOW + timedelta(days=7),
        fee_rate=77.27,
        failed_count=2,
        thumbnail_url=None,
    ),
    AuctionListItem(
        id=1002,
        source=AuctionSource.ONBID,
        asset_type=AssetType.REALTY,
        status=AuctionStatus.SCHEDULED,
        title="서울 종로구 오피스텔 (mock)",
        address="서울특별시 종로구 종로 1",
        region_sido="서울특별시",
        region_sigungu="종로구",
        lat=37.5704, lng=126.9810,
        appraisal_price=410_000_000,
        min_bid_price=320_000_000,
        bid_end_at=_NOW + timedelta(days=14),
        fee_rate=78.05,
    ),
    AuctionListItem(
        id=1003,
        source=AuctionSource.ONBID,
        asset_type=AssetType.VEHICLE,
        status=AuctionStatus.ONGOING,
        title="74더1876 (mock)",
        address=None,
        lat=None, lng=None,
        appraisal_price=12_000_000,
        min_bid_price=9_600_000,
        bid_end_at=_NOW + timedelta(days=3),
        fee_rate=80.0,
    ),
    # ----- 클러스터링 시연용 전국 분포 매물 (mock) -----
    AuctionListItem(
        id=1101, source=AuctionSource.ONBID, asset_type=AssetType.REALTY,
        status=AuctionStatus.ONGOING, title="성남 분당 아파트 (mock)",
        address="경기도 성남시 분당구 정자동 178",
        region_sido="경기도", region_sigungu="성남시 분당구",
        lat=37.3676, lng=127.1086,
        appraisal_price=1_200_000_000, min_bid_price=960_000_000,
        bid_end_at=_NOW + timedelta(days=5), fee_rate=80.0, failed_count=1,
    ),
    AuctionListItem(
        id=1102, source=AuctionSource.ONBID, asset_type=AssetType.REALTY,
        status=AuctionStatus.SCHEDULED, title="성남 수정 아파트 (mock)",
        address="경기도 성남시 수정구 신흥동 4904",
        region_sido="경기도", region_sigungu="성남시 수정구",
        lat=37.4474, lng=127.1463,
        appraisal_price=600_000_000, min_bid_price=480_000_000,
        bid_end_at=_NOW + timedelta(days=10), fee_rate=80.0, failed_count=0,
    ),
    AuctionListItem(
        id=1103, source=AuctionSource.ONBID, asset_type=AssetType.REALTY,
        status=AuctionStatus.ONGOING, title="수원 영통 오피스텔 (mock)",
        address="경기도 수원시 영통구 매탄동 893",
        region_sido="경기도", region_sigungu="수원시 영통구",
        lat=37.2636, lng=127.0286,
        appraisal_price=380_000_000, min_bid_price=304_000_000,
        bid_end_at=_NOW + timedelta(days=4), fee_rate=80.0, failed_count=2,
    ),
    AuctionListItem(
        id=1104, source=AuctionSource.ONBID, asset_type=AssetType.REALTY,
        status=AuctionStatus.ONGOING, title="용인 수지 아파트 (mock)",
        address="경기도 용인시 수지구 풍덕천동 700",
        region_sido="경기도", region_sigungu="용인시 수지구",
        lat=37.3219, lng=127.0954,
        appraisal_price=820_000_000, min_bid_price=656_000_000,
        bid_end_at=_NOW + timedelta(days=8), fee_rate=80.0, failed_count=0,
    ),
    AuctionListItem(
        id=1105, source=AuctionSource.ONBID, asset_type=AssetType.REALTY,
        status=AuctionStatus.ONGOING, title="고양 일산 주택 (mock)",
        address="경기도 고양시 일산동구 마두동 769",
        region_sido="경기도", region_sigungu="고양시 일산동구",
        lat=37.6584, lng=126.7706,
        appraisal_price=540_000_000, min_bid_price=432_000_000,
        bid_end_at=_NOW + timedelta(days=6), fee_rate=80.0, failed_count=1,
    ),
    AuctionListItem(
        id=1106, source=AuctionSource.ONBID, asset_type=AssetType.REALTY,
        status=AuctionStatus.ONGOING, title="안양 동안 아파트 (mock)",
        address="경기도 안양시 동안구 비산동 1107",
        region_sido="경기도", region_sigungu="안양시 동안구",
        lat=37.3925, lng=126.9568,
        appraisal_price=720_000_000, min_bid_price=576_000_000,
        bid_end_at=_NOW + timedelta(days=12), fee_rate=80.0, failed_count=0,
    ),
    AuctionListItem(
        id=1107, source=AuctionSource.ONBID, asset_type=AssetType.REALTY,
        status=AuctionStatus.ONGOING, title="부산 해운대 아파트 (mock)",
        address="부산광역시 해운대구 우동 1411",
        region_sido="부산광역시", region_sigungu="해운대구",
        lat=35.1631, lng=129.1635,
        appraisal_price=1_400_000_000, min_bid_price=1_120_000_000,
        bid_end_at=_NOW + timedelta(days=9), fee_rate=80.0, failed_count=0,
    ),
    AuctionListItem(
        id=1108, source=AuctionSource.ONBID, asset_type=AssetType.REALTY,
        status=AuctionStatus.SCHEDULED, title="부산 수영 오피스텔 (mock)",
        address="부산광역시 수영구 광안동 192",
        region_sido="부산광역시", region_sigungu="수영구",
        lat=35.1450, lng=129.1133,
        appraisal_price=420_000_000, min_bid_price=336_000_000,
        bid_end_at=_NOW + timedelta(days=15), fee_rate=80.0, failed_count=1,
    ),
    AuctionListItem(
        id=1109, source=AuctionSource.ONBID, asset_type=AssetType.REALTY,
        status=AuctionStatus.ONGOING, title="대구 수성 아파트 (mock)",
        address="대구광역시 수성구 범어동 175",
        region_sido="대구광역시", region_sigungu="수성구",
        lat=35.8579, lng=128.6307,
        appraisal_price=910_000_000, min_bid_price=728_000_000,
        bid_end_at=_NOW + timedelta(days=11), fee_rate=80.0, failed_count=0,
    ),
    AuctionListItem(
        id=1110, source=AuctionSource.ONBID, asset_type=AssetType.REALTY,
        status=AuctionStatus.ONGOING, title="인천 연수 아파트 (mock)",
        address="인천광역시 연수구 송도동 6",
        region_sido="인천광역시", region_sigungu="연수구",
        lat=37.4106, lng=126.6783,
        appraisal_price=860_000_000, min_bid_price=688_000_000,
        bid_end_at=_NOW + timedelta(days=7), fee_rate=80.0, failed_count=2,
    ),
    AuctionListItem(
        id=1111, source=AuctionSource.ONBID, asset_type=AssetType.REALTY,
        status=AuctionStatus.ONGOING, title="광주 서구 아파트 (mock)",
        address="광주광역시 서구 화정동 685",
        region_sido="광주광역시", region_sigungu="서구",
        lat=35.1525, lng=126.8902,
        appraisal_price=480_000_000, min_bid_price=384_000_000,
        bid_end_at=_NOW + timedelta(days=13), fee_rate=80.0, failed_count=0,
    ),
    AuctionListItem(
        id=1112, source=AuctionSource.ONBID, asset_type=AssetType.REALTY,
        status=AuctionStatus.ONGOING, title="대전 유성 아파트 (mock)",
        address="대전광역시 유성구 봉명동 555",
        region_sido="대전광역시", region_sigungu="유성구",
        lat=36.3623, lng=127.3565,
        appraisal_price=560_000_000, min_bid_price=448_000_000,
        bid_end_at=_NOW + timedelta(days=6), fee_rate=80.0, failed_count=1,
    ),
    AuctionListItem(
        id=1113, source=AuctionSource.ONBID, asset_type=AssetType.REALTY,
        status=AuctionStatus.ONGOING, title="울산 남구 아파트 (mock)",
        address="울산광역시 남구 삼산동 1480",
        region_sido="울산광역시", region_sigungu="남구",
        lat=35.5439, lng=129.3299,
        appraisal_price=520_000_000, min_bid_price=416_000_000,
        bid_end_at=_NOW + timedelta(days=10), fee_rate=80.0, failed_count=0,
    ),
    AuctionListItem(
        id=1114, source=AuctionSource.ONBID, asset_type=AssetType.REALTY,
        status=AuctionStatus.SCHEDULED, title="춘천 주택 (mock)",
        address="강원도 춘천시 효자동 651",
        region_sido="강원도", region_sigungu="춘천시",
        lat=37.8813, lng=127.7298,
        appraisal_price=320_000_000, min_bid_price=256_000_000,
        bid_end_at=_NOW + timedelta(days=18), fee_rate=80.0, failed_count=1,
    ),
    AuctionListItem(
        id=1115, source=AuctionSource.ONBID, asset_type=AssetType.REALTY,
        status=AuctionStatus.ONGOING, title="천안 동남 아파트 (mock)",
        address="충청남도 천안시 동남구 신부동 422",
        region_sido="충청남도", region_sigungu="천안시 동남구",
        lat=36.8055, lng=127.1472,
        appraisal_price=410_000_000, min_bid_price=328_000_000,
        bid_end_at=_NOW + timedelta(days=9), fee_rate=80.0, failed_count=0,
    ),
    AuctionListItem(
        id=1116, source=AuctionSource.ONBID, asset_type=AssetType.REALTY,
        status=AuctionStatus.ONGOING, title="청주 흥덕 아파트 (mock)",
        address="충청북도 청주시 흥덕구 가경동 1411",
        region_sido="충청북도", region_sigungu="청주시 흥덕구",
        lat=36.6359, lng=127.4570,
        appraisal_price=380_000_000, min_bid_price=304_000_000,
        bid_end_at=_NOW + timedelta(days=8), fee_rate=80.0, failed_count=2,
    ),
    AuctionListItem(
        id=1117, source=AuctionSource.ONBID, asset_type=AssetType.REALTY,
        status=AuctionStatus.ONGOING, title="전주 완산 주택 (mock)",
        address="전라북도 전주시 완산구 효자동 1234",
        region_sido="전라북도", region_sigungu="전주시 완산구",
        lat=35.8123, lng=127.0890,
        appraisal_price=290_000_000, min_bid_price=232_000_000,
        bid_end_at=_NOW + timedelta(days=14), fee_rate=80.0, failed_count=1,
    ),
    AuctionListItem(
        id=1118, source=AuctionSource.ONBID, asset_type=AssetType.REALTY,
        status=AuctionStatus.ONGOING, title="창원 의창 아파트 (mock)",
        address="경상남도 창원시 의창구 용호동 7",
        region_sido="경상남도", region_sigungu="창원시 의창구",
        lat=35.2540, lng=128.6406,
        appraisal_price=470_000_000, min_bid_price=376_000_000,
        bid_end_at=_NOW + timedelta(days=11), fee_rate=80.0, failed_count=0,
    ),
    AuctionListItem(
        id=1119, source=AuctionSource.ONBID, asset_type=AssetType.REALTY,
        status=AuctionStatus.ONGOING, title="포항 북구 아파트 (mock)",
        address="경상북도 포항시 북구 양덕동 1909",
        region_sido="경상북도", region_sigungu="포항시 북구",
        lat=36.0337, lng=129.3654,
        appraisal_price=350_000_000, min_bid_price=280_000_000,
        bid_end_at=_NOW + timedelta(days=7), fee_rate=80.0, failed_count=1,
    ),
    AuctionListItem(
        id=1120, source=AuctionSource.ONBID, asset_type=AssetType.REALTY,
        status=AuctionStatus.ONGOING, title="제주 노형 아파트 (mock)",
        address="제주특별자치도 제주시 노형동 925",
        region_sido="제주특별자치도", region_sigungu="제주시",
        lat=33.4996, lng=126.5312,
        appraisal_price=540_000_000, min_bid_price=432_000_000,
        bid_end_at=_NOW + timedelta(days=12), fee_rate=80.0, failed_count=0,
    ),
]

# 자동차 전용 리스트/통계 mock — VehicleListItem 직접 보관
_MOCK_VEHICLES: list[VehicleListItem] = [
    VehicleListItem(
        id=2001, source=AuctionSource.ONBID, status=AuctionStatus.ONGOING,
        title="현대 그랜저 IG 2.4 (mock)",
        region_sido="서울특별시", region_sigungu="강남구",
        appraisal_price=18_000_000, min_bid_price=14_400_000,
        bid_begin_at=_NOW - timedelta(days=1),
        bid_end_at=_NOW + timedelta(days=6),
        fee_rate=80.0, failed_count=0,
        vehicle_category=VehicleCategory.SEDAN,
        maker="현대자동차", model_name="그랜저 IG", year_model="2019",
        mileage_km=86_500, displacement_cc=2359,
        transmission="자동", fuel="휘발유",
    ),
    VehicleListItem(
        id=2002, source=AuctionSource.ONBID, status=AuctionStatus.SCHEDULED,
        title="기아 K5 DL3 (mock)",
        region_sido="경기도", region_sigungu="성남시 분당구",
        appraisal_price=22_000_000, min_bid_price=17_600_000,
        bid_begin_at=_NOW - timedelta(hours=12),
        bid_end_at=_NOW + timedelta(days=8),
        fee_rate=80.0, failed_count=0,
        vehicle_category=VehicleCategory.SEDAN,
        maker="기아", model_name="K5 DL3", year_model="2022",
        mileage_km=24_300, displacement_cc=1999,
        transmission="자동", fuel="휘발유",
    ),
    VehicleListItem(
        id=2003, source=AuctionSource.ONBID, status=AuctionStatus.ONGOING,
        title="현대 포터2 (mock)",
        region_sido="부산광역시", region_sigungu="해운대구",
        appraisal_price=11_000_000, min_bid_price=8_800_000,
        bid_begin_at=_NOW - timedelta(days=3),
        bid_end_at=_NOW + timedelta(days=4),
        fee_rate=80.0, failed_count=1,
        vehicle_category=VehicleCategory.TRUCK,
        maker="현대자동차", model_name="포터2", year_model="2017",
        mileage_km=152_800, displacement_cc=2497,
        transmission="수동", fuel="경유",
    ),
    VehicleListItem(
        id=2004, source=AuctionSource.ONBID, status=AuctionStatus.ONGOING,
        title="기아 카니발 KA4 (mock)",
        region_sido="인천광역시", region_sigungu="연수구",
        appraisal_price=34_000_000, min_bid_price=27_200_000,
        bid_begin_at=_NOW - timedelta(days=2),
        bid_end_at=_NOW + timedelta(days=5),
        fee_rate=80.0, failed_count=0,
        vehicle_category=VehicleCategory.VAN,
        maker="기아", model_name="카니발 KA4", year_model="2023",
        mileage_km=12_900, displacement_cc=2199,
        transmission="자동", fuel="경유",
    ),
    VehicleListItem(
        id=2005, source=AuctionSource.ONBID, status=AuctionStatus.SCHEDULED,
        title="르노삼성 SM6 LPe (mock)",
        region_sido="대구광역시", region_sigungu="수성구",
        appraisal_price=14_500_000, min_bid_price=11_600_000,
        bid_begin_at=_NOW - timedelta(hours=6),
        bid_end_at=_NOW + timedelta(days=9),
        fee_rate=80.0, failed_count=2,
        vehicle_category=VehicleCategory.SEDAN,
        maker="르노삼성", model_name="SM6 LPe", year_model="2018",
        mileage_km=98_400, displacement_cc=1998,
        transmission="자동", fuel="LPG",
    ),
    VehicleListItem(
        id=2006, source=AuctionSource.ONBID, status=AuctionStatus.ONGOING,
        title="테슬라 모델3 SR+ (mock)",
        region_sido="서울특별시", region_sigungu="송파구",
        appraisal_price=42_000_000, min_bid_price=33_600_000,
        bid_begin_at=_NOW - timedelta(hours=2),
        bid_end_at=_NOW + timedelta(days=10),
        fee_rate=80.0, failed_count=0,
        vehicle_category=VehicleCategory.SEDAN,
        maker="테슬라", model_name="모델3 SR+", year_model="2021",
        mileage_km=38_700, displacement_cc=None,
        transmission="자동", fuel="전기",
    ),
    VehicleListItem(
        id=2007, source=AuctionSource.ONBID, status=AuctionStatus.ONGOING,
        title="혼다 PCX 125 (mock)",
        region_sido="서울특별시", region_sigungu="마포구",
        appraisal_price=2_400_000, min_bid_price=1_920_000,
        bid_begin_at=_NOW - timedelta(days=5),
        bid_end_at=_NOW + timedelta(days=2),
        fee_rate=80.0, failed_count=1,
        vehicle_category=VehicleCategory.MOTORCYCLE,
        maker="혼다", model_name="PCX 125", year_model="2020",
        mileage_km=8_500, displacement_cc=124,
        transmission="자동", fuel="휘발유",
    ),
    VehicleListItem(
        id=2008, source=AuctionSource.ONBID, status=AuctionStatus.ONGOING,
        title="현대 스타리아 (mock)",
        region_sido="경기도", region_sigungu="수원시 영통구",
        appraisal_price=29_000_000, min_bid_price=23_200_000,
        bid_begin_at=_NOW - timedelta(days=4),
        bid_end_at=_NOW + timedelta(days=3),
        fee_rate=80.0, failed_count=0,
        vehicle_category=VehicleCategory.VAN,
        maker="현대자동차", model_name="스타리아", year_model="2022",
        mileage_km=42_310, displacement_cc=2199,
        transmission="자동", fuel="경유",
    ),
]


_MOCK_ASSET_COUNTS: dict[AssetType, int] = {
    AssetType.REALTY: 2890,
    AssetType.VEHICLE: 612,
    AssetType.MOVABLE: 281,
}
_MOCK_REALTY_CAT: dict[PropertyCategory, int] = {
    PropertyCategory.APARTMENT: 1284,
    PropertyCategory.OFFICETEL: 421,
    PropertyCategory.VILLA: 612,
    PropertyCategory.HOUSE: 387,
    PropertyCategory.COMMERCIAL: 256,
    PropertyCategory.LAND: 198,
    PropertyCategory.ETC: 73,
}
_MOCK_VEHICLE_CAT: dict[VehicleCategory, int] = {
    VehicleCategory.SEDAN: 318,
    VehicleCategory.VAN: 147,
    VehicleCategory.TRUCK: 92,
    VehicleCategory.BUS: 21,
    VehicleCategory.MOTORCYCLE: 18,
    VehicleCategory.SPECIAL: 11,
    VehicleCategory.ETC: 5,
}
_MOCK_SOURCE_COUNTS: dict[AuctionSource, int] = {
    AuctionSource.ONBID: 3402,
    AuctionSource.COURT: 0,
}


class MockAuctionRepository(AuctionRepository):
    async def get_stats(self) -> AuctionStatsResponse:
        groups = [
            AssetGroupStat(
                asset_type=AssetType.REALTY,
                label=ASSET_TYPE_LABELS_KO[AssetType.REALTY],
                total=_MOCK_ASSET_COUNTS[AssetType.REALTY],
                categories=[
                    CategorySubStat(
                        key=cat.value,
                        label=PROPERTY_CATEGORY_LABELS_KO[cat],
                        count=_MOCK_REALTY_CAT.get(cat, 0),
                    )
                    for cat in PropertyCategory
                ],
            ),
            AssetGroupStat(
                asset_type=AssetType.VEHICLE,
                label=ASSET_TYPE_LABELS_KO[AssetType.VEHICLE],
                total=_MOCK_ASSET_COUNTS[AssetType.VEHICLE],
                categories=[
                    CategorySubStat(
                        key=cat.value,
                        label=VEHICLE_CATEGORY_LABELS_KO[cat],
                        count=_MOCK_VEHICLE_CAT.get(cat, 0),
                    )
                    for cat in VehicleCategory
                ],
            ),
            AssetGroupStat(
                asset_type=AssetType.MOVABLE,
                label=ASSET_TYPE_LABELS_KO[AssetType.MOVABLE],
                total=_MOCK_ASSET_COUNTS[AssetType.MOVABLE],
                categories=[],
            ),
        ]
        by_source = [
            SourceStat(source=src, count=_MOCK_SOURCE_COUNTS[src])
            for src in AuctionSource
        ]
        return AuctionStatsResponse(
            total=sum(_MOCK_ASSET_COUNTS.values()),
            groups=groups,
            by_source=by_source,
        )

    async def get_in_bbox(
        self,
        min_lng,
        min_lat,
        max_lng,
        max_lat,
        asset_type=None,
        property_category=None,
        vehicle_category=None,
        status=None,
        limit=200,
    ):
        result = []
        for a in _MOCK_ITEMS:
            if a.lng is None or a.lat is None:
                continue
            if not (min_lng <= a.lng <= max_lng and min_lat <= a.lat <= max_lat):
                continue
            if asset_type is not None and a.asset_type != asset_type:
                continue
            if status is not None and a.status != status:
                continue
            result.append(a)
        return result[:limit]

    async def get_by_id(self, auction_id: int) -> AuctionDetail | None:
        item = next((a for a in _MOCK_ITEMS if a.id == auction_id), None)
        if item is None:
            return None

        details = None
        if item.asset_type == AssetType.REALTY:
            details = RealtyDetails(
                property_category=PropertyCategory.APARTMENT,
                land_sqms=84.46,
                bld_sqms=59.75,
                alc_yn=False,
            )
        elif item.asset_type == AssetType.VEHICLE:
            details = VehicleDetails(
                vehicle_category=VehicleCategory.VAN,
                maker="현대자동차",
                vehicle_kind="승합",
                model_name="스타리아",
                year_model="2022",
                plate_no="74더1876",
                mileage_km=42_310,
                displacement_cc=2199,
                transmission="자동",
                fuel="경유",
                color="흰색",
                quantity_text="1대",
            )

        return AuctionDetail(
            id=item.id,
            source=item.source,
            asset_type=item.asset_type,
            status=item.status,
            title=item.title,
            cltr_mng_no=f"MOCK-{item.id}",
            pbct_cdtn_no=item.id * 1000,
            address=item.address,
            region_sido=item.region_sido,
            region_sigungu=item.region_sigungu,
            lat=item.lat, lng=item.lng,
            appraisal_price=item.appraisal_price,
            min_bid_price=item.min_bid_price,
            fee_rate=item.fee_rate,
            bid_end_at=item.bid_end_at,
            failed_count=item.failed_count,
            announce_org_nm="한국자산관리공사 (mock)",
            thumbnail_url=item.thumbnail_url,
            details=details,
            rights_analysis=RightsAnalysisSummary(
                summary="권리 관계 단순 (mock).",
                risk_level=1,
                rights_data={},
            ),
        )

    # ----- AuctionRepository extra methods (no-op for mock) -----

    async def upsert_many(
        self, items: list[AuctionUpsertItem]
    ) -> tuple[int, int]:
        return (len(items), 0)

    async def list_realty_missing_images(
        self, limit: int
    ) -> list[tuple[int, str, int]]:
        return []

    async def list_movable_missing_images(
        self, limit: int
    ) -> list[tuple[int, str, int]]:
        return []

    async def list_auctions_missing_bid_info(
        self, limit: int
    ) -> list[tuple[int, str, int]]:
        return []

    async def update_bid_info(
        self, auction_id: int, bid_info: dict
    ) -> None:
        return None

    async def lookup_active_auction_ids(
        self, keys: list[tuple[str, int]]
    ) -> dict[tuple[str, int], int]:
        return {}

    async def update_image_urls(
        self, auction_id: int, image_urls: list[str]
    ) -> None:
        return None

    async def list_auctions_pending_results(
        self, limit: int
    ) -> list[tuple[int, str, int]]:
        return []

    async def upsert_bid_result(self, auction_id: int, payload) -> None:
        return None

    async def list_auctions_missing_pbanc_mng_no(
        self, limit: int,
    ) -> list[PbancResolveTarget]:
        return []

    async def update_pbanc_mng_no_batch(
        self, mapping: list[tuple[int, str]],
    ) -> int:
        return 0

    async def list_pbanc_groups_for_round_enrich(
        self, limit: int,
    ) -> list[PbancEnrichGroup]:
        return []

    async def get_sibling_for_cltr(self, cltr_mng_no: str):
        return (None, set(), None)

    async def list_vehicles(
        self, q: VehicleListQuery
    ) -> tuple[list[VehicleListItem], int]:
        def _matches(v: VehicleListItem) -> bool:
            if q.vehicle_category is not None and v.vehicle_category != q.vehicle_category:
                return False
            if q.maker and (v.maker is None or q.maker.lower() not in v.maker.lower()):
                return False
            if q.fuel and (v.fuel is None or q.fuel.lower() not in v.fuel.lower()):
                return False
            if q.transmission and (
                v.transmission is None
                or q.transmission.lower() not in v.transmission.lower()
            ):
                return False
            if q.year_model_min and (v.year_model is None or v.year_model < q.year_model_min):
                return False
            if q.year_model_max and (v.year_model is None or v.year_model > q.year_model_max):
                return False
            if q.mileage_km_min is not None and (
                v.mileage_km is None or v.mileage_km < q.mileage_km_min
            ):
                return False
            if q.mileage_km_max is not None and (
                v.mileage_km is None or v.mileage_km > q.mileage_km_max
            ):
                return False
            if q.displacement_cc_min is not None and (
                v.displacement_cc is None or v.displacement_cc < q.displacement_cc_min
            ):
                return False
            if q.displacement_cc_max is not None and (
                v.displacement_cc is None or v.displacement_cc > q.displacement_cc_max
            ):
                return False
            if q.status is not None and v.status != q.status:
                return False
            if q.region_sido and v.region_sido != q.region_sido:
                return False
            return True

        matched = [v for v in _MOCK_VEHICLES if _matches(v)]
        matched.sort(
            key=lambda v: (
                v.bid_begin_at is None,
                # bid_begin_at DESC + id DESC tiebreaker
                -(v.bid_begin_at.timestamp() if v.bid_begin_at else 0),
                -v.id,
            )
        )
        sliced = matched[q.offset : q.offset + q.limit]
        return sliced, len(matched)

    async def get_vehicle_stats(self) -> VehicleStatsResponse:
        active = [
            v for v in _MOCK_VEHICLES
            if v.status in (AuctionStatus.SCHEDULED, AuctionStatus.ONGOING)
        ]

        def _facet_counts(key_fn) -> list[tuple[str, int]]:
            buckets: dict[str, int] = {}
            for v in active:
                k = key_fn(v)
                if k is None or k == "":
                    continue
                buckets[k] = buckets.get(k, 0) + 1
            return sorted(buckets.items(), key=lambda kv: -kv[1])

        cat_buckets: dict[VehicleCategory, int] = {}
        for v in active:
            cat_buckets[v.vehicle_category] = cat_buckets.get(v.vehicle_category, 0) + 1

        return VehicleStatsResponse(
            total=len(active),
            by_category=[
                VehicleFacetCount(
                    key=cat.value,
                    label=VEHICLE_CATEGORY_LABELS_KO.get(cat),
                    count=cnt,
                )
                for cat, cnt in cat_buckets.items()
            ],
            by_fuel=[
                VehicleFacetCount(key=k, label=k, count=c)
                for k, c in _facet_counts(lambda v: v.fuel)
            ],
            by_transmission=[
                VehicleFacetCount(key=k, label=k, count=c)
                for k, c in _facet_counts(lambda v: v.transmission)
            ],
            by_maker_top=[
                VehicleMakerCount(maker=k, count=c)
                for k, c in _facet_counts(lambda v: v.maker)[:20]
            ],
            by_year_model=sorted(
                [
                    VehicleYearBucket(year_model=k, count=c)
                    for k, c in _facet_counts(lambda v: v.year_model)
                ],
                key=lambda b: b.year_model,
                reverse=True,
            ),
        )
