from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_auction_service
from app.domain.auction.schemas import (
    AssetType,
    BidResultKind,
    BidResultListQuery,
    BidResultListResponse,
    BidResultSort,
    PropertyCategory,
)
from app.domain.auction.service import AuctionService

router = APIRouter(prefix="/bid-results", tags=["bid-results"])


@router.get(
    "",
    response_model=BidResultListResponse,
    summary="매각결과 목록 (낙찰가·낙찰가율·입찰자수, 개찰일 최신순)",
)
async def list_bid_results(
    asset_type: AssetType | None = Query(None, description="realty/movable/vehicle"),
    property_category: list[PropertyCategory] | None = Query(
        None, description="realty 전용 — 반복 지정 시 OR",
    ),
    region_sido: str | None = Query(None, max_length=20),
    region_sigungu: str | None = Query(None, max_length=30),
    result: BidResultKind | None = Query(
        None, description="sold(낙찰)/failed(유찰)/cancelled(취소)",
    ),
    opbd_from: date | None = Query(None, description="개찰일 하한 (YYYY-MM-DD)"),
    opbd_to: date | None = Query(None, description="개찰일 상한 (YYYY-MM-DD)"),
    sort: BidResultSort = Query(BidResultSort.OPBD_AT_DESC),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    service: AuctionService = Depends(get_auction_service),
) -> BidResultListResponse:
    try:
        q = BidResultListQuery(
            asset_type=asset_type,
            property_category=property_category,
            region_sido=region_sido,
            region_sigungu=region_sigungu,
            result=result,
            opbd_from=opbd_from,
            opbd_to=opbd_to,
            sort=sort,
            offset=offset,
            limit=limit,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return await service.list_bid_results(q)
