from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
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


# =====================================================================
# Pbanc enrichment DTOs (D안: 공고 API 체인으로 누락 회차 보강)
# =====================================================================
@dataclass(slots=True)
class PbancResolveTarget:
    """pbanc_mng_no가 미해결(NULL)인 active onbid 매물 한 건."""
    auction_id: int
    onbid_pbanc_no: int
    asset_type: AssetType
    bid_begin_at: datetime | None  # getPbancList2의 bidPrdYmd 검색 키


@dataclass(slots=True)
class AuctionSiblingMeta:
    """같은 cltr_mng_no의 기존 회차에서 상속받을 cltr-stable 메타.

    공고 응답(getPbancCltrInf2)은 회차별 입찰가/일정/상태만 풍부하고
    주소/지오코딩/PNU/카테고리는 빠진다. 새 회차 row를 만들 때 같은 cltr의
    sibling row에서 이 값들을 그대로 들고 와 채워 넣는다.
    """
    asset_type: AssetType
    region_sido: str | None
    region_sigungu: str | None
    region_emd: str | None
    address: str | None
    lat: float | None
    lng: float | None
    ltno_pnu: str | None
    rdnm_pnu: str | None
    request_org_nm: str | None
    announce_org_nm: str | None
    thumbnail_url: str | None
    property_category: PropertyCategory | None  # realty일 때만 의미 있음


@dataclass(slots=True)
class PbancEnrichGroup:
    """회차 보강 대상 공고 1건 + 이미 보유한 회차 키 + 상속용 sibling 메타."""
    pbanc_mng_no: str
    existing_keys: set[tuple[str, int]] = field(default_factory=set)
    siblings: dict[str, AuctionSiblingMeta] = field(default_factory=dict)


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

    @abstractmethod
    async def list_auctions_missing_pbanc_mng_no(
        self, limit: int,
    ) -> list[PbancResolveTarget]:
        """pbanc_mng_no가 NULL인 active onbid 매물 N건 — Phase A 대상."""
        ...

    @abstractmethod
    async def update_pbanc_mng_no_batch(
        self, mapping: list[tuple[int, str]],
    ) -> int:
        """auction_id → pbanc_mng_no 일괄 업데이트. 갱신된 row 수 반환."""
        ...

    @abstractmethod
    async def list_pbanc_groups_for_round_enrich(
        self, limit: int,
    ) -> list[PbancEnrichGroup]:
        """pbanc_mng_no가 해결된 active 매물의 distinct 공고 그룹 — Phase B 대상.

        각 그룹은 이미 보유한 (cltr, pbct) 키 집합과, 새 회차 row 생성용
        sibling 메타(cltr_mng_no → AuctionSiblingMeta)를 포함.
        """
        ...

    @abstractmethod
    async def get_sibling_for_cltr(
        self, cltr_mng_no: str,
    ) -> tuple[AuctionSiblingMeta | None, set[int], str | None]:
        """단일 cltr_mng_no의 sibling 메타 + 이미 보유한 pbct_cdtn_no 집합 + pbanc_mng_no.

        pbanc_mng_no는 회차들이 공유하므로 임의의 1개 row 값을 그대로 반환.
        cltr가 DB에 없으면 (None, set(), None).
        """
        ...
