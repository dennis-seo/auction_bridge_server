from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from app.domain.auction.schemas import (
    AssetType,
    AuctionDetail,
    AuctionListItem,
    AuctionStatsResponse,
    AuctionStatus,
    AuctionUpsertItem,
    PropertyCategory,
    VehicleCategory,
    VehicleListItem,
    VehicleListQuery,
    VehicleStatsResponse,
)

if TYPE_CHECKING:
    from app.services.onbid_ingest_service import BidResultPayload


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
    async def list_movable_missing_images(
        self, limit: int
    ) -> list[tuple[int, str, int]]:
        """이미지 미보강 동산 N건 반환 — (auction_id, cltr_mng_no, pbct_cdtn_no)."""
        ...

    @abstractmethod
    async def list_auctions_missing_bid_info(
        self, limit: int
    ) -> list[tuple[int, str, int]]:
        """bid_info(#7) 미보강 active 매물 N건 — (auction_id, cltr_mng_no, pbct_cdtn_no)."""
        ...

    @abstractmethod
    async def update_bid_info(
        self, auction_id: int, bid_info: dict
    ) -> None:
        """#7 응답 dict를 auctions.bid_info에 저장."""
        ...

    @abstractmethod
    async def lookup_active_auction_ids(
        self, keys: list[tuple[str, int]]
    ) -> dict[tuple[str, int], int]:
        """(cltr_mng_no, pbct_cdtn_no) 리스트를 받아 active(ongoing/scheduled) 매물의
        auction_id를 dict로 반환. 결과 미확정 매물만 매칭하도록 필터."""
        ...

    @abstractmethod
    async def update_image_urls(
        self, auction_id: int, image_urls: list[str]
    ) -> None:
        ...

    @abstractmethod
    async def list_auctions_pending_results(
        self, limit: int
    ) -> list[tuple[int, str, int]]:
        """결과 미확정 ongoing 매물 N건 — bid_end_at 지난 것부터.

        Returns: list of (auction_id, cltr_mng_no, pbct_cdtn_no).
        """
        ...

    @abstractmethod
    async def upsert_bid_result(
        self, auction_id: int, payload: "BidResultPayload"
    ) -> None:
        """auction_bid_results upsert + auctions.status를 결과에 맞춰 갱신."""
        ...

    @abstractmethod
    async def list_vehicles(
        self, q: VehicleListQuery
    ) -> tuple[list[VehicleListItem], int]:
        """필터된 차량 리스트 + 총 매칭 건수 — (items, total)."""
        ...

    @abstractmethod
    async def get_vehicle_stats(self) -> VehicleStatsResponse:
        """진행 중 차량 매물의 카테고리/연료/변속기/maker/연식 facet."""
        ...
