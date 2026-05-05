from datetime import datetime, timedelta, timezone

from app.domain.auction.repository import AuctionRepository
from app.domain.auction.schemas import (
    PROPERTY_CATEGORY_LABELS_KO,
    AuctionDetail,
    AuctionListItem,
    AuctionSource,
    AuctionStatsResponse,
    AuctionStatus,
    AuctionUpsertItem,
    CategoryStat,
    PropertyCategory,
    RightsAnalysisSummary,
    SourceStat,
)


_MOCK_CATEGORY_COUNTS: dict[PropertyCategory, int] = {
    PropertyCategory.APARTMENT: 1284,
    PropertyCategory.VILLA: 612,
    PropertyCategory.HOUSE: 387,
    PropertyCategory.OFFICETEL: 421,
    PropertyCategory.COMMERCIAL: 256,
    PropertyCategory.LAND: 198,
    PropertyCategory.ETC: 73,
}

_MOCK_SOURCE_COUNTS: dict[AuctionSource, int] = {
    AuctionSource.COURT: 2390,
    AuctionSource.ONBID: 841,
}


# 서울 시청 주변 — 지도 BBox 검증용 가짜 마커
_NOW = datetime.now(timezone.utc)
_MOCK_AUCTIONS: list[AuctionListItem] = [
    AuctionListItem(
        id=1001,
        source=AuctionSource.ONBID,
        category=PropertyCategory.APARTMENT,
        status=AuctionStatus.ONGOING,
        title="서울 중구 아파트 (mock)",
        address="서울특별시 중구 세종대로 110",
        lat=37.5665,
        lng=126.9780,
        minimum_bid_price=850_000_000,
        appraisal_price=1_100_000_000,
        auction_date=_NOW + timedelta(days=7),
    ),
    AuctionListItem(
        id=1002,
        source=AuctionSource.ONBID,
        category=PropertyCategory.OFFICETEL,
        status=AuctionStatus.SCHEDULED,
        title="서울 종로구 오피스텔 (mock)",
        address="서울특별시 종로구 종로 1",
        lat=37.5704,
        lng=126.9810,
        minimum_bid_price=320_000_000,
        appraisal_price=410_000_000,
        auction_date=_NOW + timedelta(days=14),
    ),
    AuctionListItem(
        id=1003,
        source=AuctionSource.COURT,
        category=PropertyCategory.COMMERCIAL,
        status=AuctionStatus.ONGOING,
        title="서울 강남구 상가 (mock)",
        address="서울특별시 강남구 테헤란로 100",
        lat=37.5045,
        lng=127.0470,
        minimum_bid_price=2_100_000_000,
        appraisal_price=2_800_000_000,
        auction_date=_NOW + timedelta(days=3),
    ),
]


class MockAuctionRepository(AuctionRepository):
    async def get_stats(self) -> AuctionStatsResponse:
        categories = [
            CategoryStat(
                key=cat,
                label=PROPERTY_CATEGORY_LABELS_KO[cat],
                count=count,
            )
            for cat, count in _MOCK_CATEGORY_COUNTS.items()
        ]
        by_source = [
            SourceStat(source=src, count=count)
            for src, count in _MOCK_SOURCE_COUNTS.items()
        ]
        total = sum(_MOCK_SOURCE_COUNTS.values())
        return AuctionStatsResponse(
            total=total, categories=categories, by_source=by_source
        )

    async def get_in_bbox(
        self,
        min_lng: float,
        min_lat: float,
        max_lng: float,
        max_lat: float,
        category: PropertyCategory | None = None,
        status: AuctionStatus | None = None,
        limit: int = 200,
    ) -> list[AuctionListItem]:
        result = [
            a for a in _MOCK_AUCTIONS
            if min_lng <= a.lng <= max_lng and min_lat <= a.lat <= max_lat
        ]
        if category is not None:
            result = [a for a in result if a.category == category]
        if status is not None:
            result = [a for a in result if a.status == status]
        return result[:limit]

    async def get_by_id(self, auction_id: int) -> AuctionDetail | None:
        item = next((a for a in _MOCK_AUCTIONS if a.id == auction_id), None)
        if item is None:
            return None
        return AuctionDetail(
            id=item.id,
            source=item.source,
            external_id=f"MOCK-{item.id}",
            case_number=f"2025타경{item.id}",
            category=item.category,
            status=item.status,
            title=item.title,
            address=item.address,
            lat=item.lat,
            lng=item.lng,
            appraisal_price=item.appraisal_price,
            minimum_bid_price=item.minimum_bid_price,
            auction_date=item.auction_date,
            agency_name="한국자산관리공사 (mock)",
            description="이것은 mock 데이터입니다. USE_MOCK=false로 전환하면 실제 DB를 조회합니다.",
            rights_analysis=RightsAnalysisSummary(
                summary="권리 관계 단순 (mock).",
                risk_level=1,
                rights_data={},
            ),
        )

    async def upsert_many(
        self, items: list[AuctionUpsertItem]
    ) -> tuple[int, int]:
        # mock에서는 실제 저장 안 함 — 호출 가능성 자체만 보장.
        return (len(items), 0)
