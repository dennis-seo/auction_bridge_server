from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class AuctionSource(str, Enum):
    COURT = "court"   # 법원 경매
    ONBID = "onbid"   # 캠코 온비드 (공매)


class AuctionStatus(str, Enum):
    SCHEDULED = "scheduled"   # 신건/예정
    ONGOING = "ongoing"       # 진행중
    SOLD = "sold"             # 매각/낙찰
    FAILED = "failed"         # 유찰
    CANCELLED = "cancelled"   # 취하/변경


class PropertyCategory(str, Enum):
    APARTMENT = "apartment"
    VILLA = "villa"
    HOUSE = "house"
    OFFICETEL = "officetel"
    COMMERCIAL = "commercial"
    LAND = "land"
    ETC = "etc"


PROPERTY_CATEGORY_LABELS_KO: dict[PropertyCategory, str] = {
    PropertyCategory.APARTMENT: "아파트",
    PropertyCategory.VILLA: "빌라/연립",
    PropertyCategory.HOUSE: "단독/다가구",
    PropertyCategory.OFFICETEL: "오피스텔",
    PropertyCategory.COMMERCIAL: "상가/업무",
    PropertyCategory.LAND: "토지",
    PropertyCategory.ETC: "기타",
}


# ---------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------
class CategoryStat(BaseModel):
    key: PropertyCategory
    label: str = Field(description="한국어 표시명")
    count: int = Field(ge=0, description="해당 카테고리의 진행 중인 매물 수")


class SourceStat(BaseModel):
    source: AuctionSource
    count: int = Field(ge=0)


class AuctionStatsResponse(BaseModel):
    total: int = Field(description="진행 중인 전체 매물 수")
    categories: list[CategoryStat]
    by_source: list[SourceStat]


# ---------------------------------------------------------------------
# Map / List / Detail
# ---------------------------------------------------------------------
class AuctionListItem(BaseModel):
    """지도 마커용 경량 페이로드."""
    id: int
    source: AuctionSource
    category: PropertyCategory
    status: AuctionStatus
    title: str | None = None
    address: str
    lat: float
    lng: float
    minimum_bid_price: int | None = None
    appraisal_price: int | None = None
    auction_date: datetime | None = None


class AuctionListResponse(BaseModel):
    items: list[AuctionListItem]
    truncated: bool = Field(
        default=False,
        description="True면 limit에 의해 잘렸다는 뜻 — 클라이언트가 줌인 유도",
    )


class RightsAnalysisSummary(BaseModel):
    summary: str | None = None
    risk_level: int | None = Field(default=None, ge=1, le=3)
    rights_data: dict[str, Any] = Field(default_factory=dict)


class AuctionDetail(BaseModel):
    id: int
    source: AuctionSource
    external_id: str
    case_number: str | None = None
    category: PropertyCategory
    status: AuctionStatus
    title: str | None = None
    address: str
    address_detail: str | None = None
    region_sido: str | None = None
    region_sigungu: str | None = None
    lat: float | None = None
    lng: float | None = None
    appraisal_price: int | None = None
    minimum_bid_price: int | None = None
    bid_deposit: int | None = None
    auction_date: datetime | None = None
    failed_count: int = 0
    court_name: str | None = None
    agency_name: str | None = None
    description: str | None = None
    rights_analysis: RightsAnalysisSummary | None = None


# ---------------------------------------------------------------------
# Ingest pipeline DTO (외부 API → DB 적재용 정규화 모델)
# ---------------------------------------------------------------------
class AuctionUpsertItem(BaseModel):
    source: AuctionSource
    external_id: str
    category: PropertyCategory
    status: AuctionStatus = AuctionStatus.SCHEDULED
    case_number: str | None = None
    title: str | None = None
    address: str
    address_detail: str | None = None
    region_sido: str | None = None
    region_sigungu: str | None = None
    lat: float | None = None
    lng: float | None = None
    appraisal_price: int | None = None
    minimum_bid_price: int | None = None
    bid_deposit: int | None = None
    auction_date: datetime | None = None
    failed_count: int = 0
    court_name: str | None = None
    agency_name: str | None = None
    description: str | None = None
    raw: dict[str, Any] = Field(
        default_factory=dict,
        description="원본 응답 — auctions.metadata JSONB로 저장",
    )


# ---------------------------------------------------------------------
# Query params
# ---------------------------------------------------------------------
class BBoxQuery(BaseModel):
    min_lng: float = Field(ge=-180, le=180)
    min_lat: float = Field(ge=-90, le=90)
    max_lng: float = Field(ge=-180, le=180)
    max_lat: float = Field(ge=-90, le=90)
    category: PropertyCategory | None = None
    status: AuctionStatus | None = None
    limit: int = Field(default=200, ge=1, le=500)

    @model_validator(mode="after")
    def _check_bounds(self) -> "BBoxQuery":
        if self.min_lng >= self.max_lng:
            raise ValueError("min_lng must be < max_lng")
        if self.min_lat >= self.max_lat:
            raise ValueError("min_lat must be < max_lat")
        return self
