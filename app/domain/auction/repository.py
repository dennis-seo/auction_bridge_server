from abc import ABC, abstractmethod

from app.domain.auction.schemas import (
    AssetType,
    AuctionDetail,
    AuctionListItem,
    AuctionStatsResponse,
    AuctionStatus,
    AuctionUpsertItem,
    PropertyCategory,
    VehicleCategory,
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
        asset_type: AssetType | None = None,
        property_category: PropertyCategory | None = None,
        vehicle_category: VehicleCategory | None = None,
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

    @abstractmethod
    async def list_realty_missing_images(
        self, limit: int
    ) -> list[tuple[int, str, int]]:
        """이미지 미보강 부동산 N건 반환 — (auction_id, cltr_mng_no, pbct_cdtn_no)."""
        ...

    @abstractmethod
    async def update_image_urls(
        self, auction_id: int, image_urls: list[str]
    ) -> None:
        ...
