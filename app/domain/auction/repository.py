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
    async def update_image_urls(
        self, auction_id: int, image_urls: list[str]
    ) -> None:
        ...

    @abstractmethod
    async def list_cltrs_needing_round_backfill(
        self, limit: int
    ) -> list[tuple[str, AssetType]]:
        """회차 누락이 의심되는 cltr_mng_no 후보 — (cltr_mng_no, asset_type).

        같은 cltr 안에서 가장 빠른 pbct_nsq가 시작 회차가 아닌 경우(예: 1회차 누락)
        를 의심해 보강 대상으로 반환.
        """
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
