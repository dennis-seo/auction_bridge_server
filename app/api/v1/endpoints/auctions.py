from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_auction_service
from app.domain.auction.schemas import (
    AssetType,
    AuctionDetail,
    AuctionListResponse,
    AuctionStatsResponse,
    AuctionStatus,
    BBoxQuery,
    PropertyCategory,
    VehicleCategory,
)
from app.domain.auction.service import AuctionService

router = APIRouter(prefix="/auctions", tags=["auctions"])


@router.get(
    "/stats",
    response_model=AuctionStatsResponse,
    summary="자산타입/카테고리별 진행 건수 (벤토 그리드용)",
)
async def get_auction_stats(
    service: AuctionService = Depends(get_auction_service),
) -> AuctionStatsResponse:
    return await service.get_stats()


@router.get(
    "",
    response_model=AuctionListResponse,
    summary="지도 BBox 안의 매물 목록 (지도 마커용)",
)
async def list_auctions_in_bbox(
    min_lng: float = Query(..., ge=-180, le=180, description="BBox 좌하 경도"),
    min_lat: float = Query(..., ge=-90, le=90, description="BBox 좌하 위도"),
    max_lng: float = Query(..., ge=-180, le=180, description="BBox 우상 경도"),
    max_lat: float = Query(..., ge=-90, le=90, description="BBox 우상 위도"),
    asset_type: AssetType | None = Query(None, description="realty/movable/vehicle"),
    property_category: PropertyCategory | None = Query(
        None, description="asset_type=realty일 때 의미 있음",
    ),
    vehicle_category: VehicleCategory | None = Query(
        None, description="asset_type=vehicle일 때 의미 있음",
    ),
    auction_status: AuctionStatus | None = Query(None, alias="status"),
    limit: int = Query(200, ge=1, le=500),
    service: AuctionService = Depends(get_auction_service),
) -> AuctionListResponse:
    try:
        q = BBoxQuery(
            min_lng=min_lng, min_lat=min_lat,
            max_lng=max_lng, max_lat=max_lat,
            asset_type=asset_type,
            property_category=property_category,
            vehicle_category=vehicle_category,
            status=auction_status,
            limit=limit,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return await service.search_in_bbox(q)


@router.get(
    "/{auction_id}",
    response_model=AuctionDetail,
    summary="매물 상세 (asset_type별 details 폴리모픽 + 권리분석)",
)
async def get_auction_detail(
    auction_id: int,
    service: AuctionService = Depends(get_auction_service),
) -> AuctionDetail:
    detail = await service.get_detail(auction_id)
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"auction {auction_id} not found",
        )
    return detail
