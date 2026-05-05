from abc import ABC, abstractmethod

from app.domain.auction.schemas import (
    AuctionDetail,
    AuctionListItem,
    AuctionStatsResponse,
    AuctionStatus,
    AuctionUpsertItem,
    PropertyCategory,
)


class AuctionRepository(ABC):
    """auctions 테이블 추상 인터페이스 — Mock/DB 구현체에서 동일 시그니처."""

    @abstractmethod
    async def get_stats(self) -> AuctionStatsResponse:
        ...

    @abstractmethod
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
        ...

    @abstractmethod
    async def get_by_id(self, auction_id: int) -> AuctionDetail | None:
        ...

    @abstractmethod
    async def upsert_many(
        self, items: list[AuctionUpsertItem]
    ) -> tuple[int, int]:
        """Returns (inserted_count, updated_count)."""
        ...
