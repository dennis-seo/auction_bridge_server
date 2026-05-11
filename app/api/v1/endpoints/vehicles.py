from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_auction_service
from app.domain.auction.schemas import (
    AuctionStatus,
    VehicleCategory,
    VehicleListQuery,
    VehicleListResponse,
    VehicleStatsResponse,
)
from app.domain.auction.service import AuctionService

router = APIRouter(prefix="/vehicles", tags=["vehicles"])


@router.get(
    "",
    response_model=VehicleListResponse,
    summary="자동차 리스트 (필터 + offset/limit 페이지네이션, 공고 시작일 최신순)",
)
async def list_vehicles(
    vehicle_category: VehicleCategory | None = Query(
        None, description="sedan/van/truck/bus/motorcycle/special/etc",
    ),
    maker: str | None = Query(None, max_length=50, description="제조사 부분 일치"),
    fuel: str | None = Query(None, max_length=20, description="연료 부분 일치"),
    transmission: str | None = Query(None, max_length=20, description="변속기 부분 일치"),
    year_model_min: str | None = Query(
        None, pattern=r"^\d{4}$", description="연식 하한 (YYYY)",
    ),
    year_model_max: str | None = Query(
        None, pattern=r"^\d{4}$", description="연식 상한 (YYYY)",
    ),
    mileage_km_min: int | None = Query(None, ge=0),
    mileage_km_max: int | None = Query(None, ge=0),
    displacement_cc_min: int | None = Query(None, ge=0),
    displacement_cc_max: int | None = Query(None, ge=0),
    auction_status: AuctionStatus | None = Query(None, alias="status"),
    region_sido: str | None = Query(None, max_length=20),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    service: AuctionService = Depends(get_auction_service),
) -> VehicleListResponse:
    try:
        q = VehicleListQuery(
            vehicle_category=vehicle_category,
            maker=maker,
            fuel=fuel,
            transmission=transmission,
            year_model_min=year_model_min,
            year_model_max=year_model_max,
            mileage_km_min=mileage_km_min,
            mileage_km_max=mileage_km_max,
            displacement_cc_min=displacement_cc_min,
            displacement_cc_max=displacement_cc_max,
            status=auction_status,
            region_sido=region_sido,
            offset=offset,
            limit=limit,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return await service.list_vehicles(q)


@router.get(
    "/stats",
    response_model=VehicleStatsResponse,
    summary="자동차 facet/통계 (카테고리/연료/변속기/maker top 20/연식)",
)
async def get_vehicle_stats(
    service: AuctionService = Depends(get_auction_service),
) -> VehicleStatsResponse:
    return await service.get_vehicle_stats()
