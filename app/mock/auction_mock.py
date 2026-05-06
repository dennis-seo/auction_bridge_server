"""Mock 구현 — 차세대 v2 스키마 기준. USE_MOCK=true일 때 사용."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.domain.auction.repository import AuctionRepository
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

    async def upsert_many(
        self, items: list[AuctionUpsertItem]
    ) -> tuple[int, int]:
        return (len(items), 0)
