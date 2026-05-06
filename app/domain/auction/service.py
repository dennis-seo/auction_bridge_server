from app.domain.auction.repository import AuctionRepository
from app.domain.auction.schemas import (
    AuctionDetail,
    AuctionListResponse,
    AuctionStatsResponse,
    BBoxQuery,
)


class AuctionService:
    def __init__(self, repo: AuctionRepository) -> None:
        self._repo = repo

    async def get_stats(self) -> AuctionStatsResponse:
        return await self._repo.get_stats()

    async def search_in_bbox(self, q: BBoxQuery) -> AuctionListResponse:
        items = await self._repo.get_in_bbox(
            min_lng=q.min_lng,
            min_lat=q.min_lat,
            max_lng=q.max_lng,
            max_lat=q.max_lat,
            asset_type=q.asset_type,
            property_category=q.property_category,
            vehicle_category=q.vehicle_category,
            status=q.status,
            limit=q.limit,
        )
        return AuctionListResponse(items=items, truncated=len(items) >= q.limit)

    async def get_detail(self, auction_id: int) -> AuctionDetail | None:
        return await self._repo.get_by_id(auction_id)
