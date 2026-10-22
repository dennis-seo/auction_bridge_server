from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_auction_service
from app.domain.auction.schemas import (
    AuctionStatus,
    PropertyCategory,
    RealtyListQuery,
    RealtyListResponse,
    RealtySort,
)
from app.domain.auction.service import AuctionService

router = APIRouter(prefix="/realty", tags=["realty"])


@router.get(
    "",
    response_model=RealtyListResponse,
    summary="부동산 목록 검색 (필터 + 정렬 + offset/limit, 대표 회차 dedup)",
)
async def list_realty(
    property_category: list[PropertyCategory] | None = Query(
        None,
        description="apartment/villa/house/officetel/commercial/land/etc — 반복 지정 시 OR",
    ),
    region_sido: str | None = Query(None, max_length=20, description="시도 정확 일치"),
    region_sigungu: str | None = Query(None, max_length=30, description="시군구 정확 일치"),
    appraisal_price_min: int | None = Query(None, ge=0, description="감정가 하한 (KRW)"),
    appraisal_price_max: int | None = Query(None, ge=0, description="감정가 상한 (KRW)"),
    min_bid_price_min: int | None = Query(None, ge=0, description="최저입찰가 하한 (KRW)"),
    min_bid_price_max: int | None = Query(None, ge=0, description="최저입찰가 상한 (KRW)"),
    failed_count_min: int | None = Query(None, ge=0, description="유찰횟수 하한"),
    failed_count_max: int | None = Query(None, ge=0, description="유찰횟수 상한"),
    land_sqms_min: float | None = Query(None, ge=0, description="토지면적 하한 (m²)"),
    land_sqms_max: float | None = Query(None, ge=0, description="토지면적 상한 (m²)"),
    bld_sqms_min: float | None = Query(None, ge=0, description="건물면적 하한 (m²)"),
    bld_sqms_max: float | None = Query(None, ge=0, description="건물면적 상한 (m²)"),
    auction_status: AuctionStatus | None = Query(None, alias="status"),
    sort: RealtySort = Query(
        RealtySort.NEWEST,
        description="newest/deadline/price_asc/price_desc/ratio_asc/failed_count",
    ),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    service: AuctionService = Depends(get_auction_service),
) -> RealtyListResponse:
    try:
        q = RealtyListQuery(
            property_category=property_category,
            region_sido=region_sido,
            region_sigungu=region_sigungu,
            appraisal_price_min=appraisal_price_min,
            appraisal_price_max=appraisal_price_max,
            min_bid_price_min=min_bid_price_min,
            min_bid_price_max=min_bid_price_max,
            failed_count_min=failed_count_min,
            failed_count_max=failed_count_max,
            land_sqms_min=land_sqms_min,
            land_sqms_max=land_sqms_max,
            bld_sqms_min=bld_sqms_min,
            bld_sqms_max=bld_sqms_max,
            status=auction_status,
            sort=sort,
            offset=offset,
            limit=limit,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return await service.list_realty(q)
