"""온비드 → 정규화 → 지오코딩 → DB upsert 파이프라인."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.domain.auction.repository import AuctionRepository
from app.domain.auction.schemas import (
    AuctionSource,
    AuctionStatus,
    AuctionUpsertItem,
    PropertyCategory,
)
from app.infrastructure.external.kakao_geocoder import KakaoGeocoder
from app.infrastructure.external.onbid_client import (
    OnbidClient,
    OnbidQuotaExceeded,
    OnbidTopCategory,
)

logger = logging.getLogger(__name__)


# 온비드 응답의 카테고리(CTGR_FULL_NM 또는 CTGR_NM) 텍스트를 PropertyCategory enum으로.
# 매칭 안 되면 ETC로 떨어뜨리고, raw는 metadata에 남아 있으므로 사후 보강 가능.
_CATEGORY_KEYWORDS: list[tuple[PropertyCategory, tuple[str, ...]]] = [
    (PropertyCategory.APARTMENT, ("아파트",)),
    (PropertyCategory.OFFICETEL, ("오피스텔",)),
    (PropertyCategory.VILLA, ("빌라", "연립", "다세대")),
    (PropertyCategory.HOUSE, ("단독", "다가구", "주택")),
    (PropertyCategory.COMMERCIAL, ("상가", "근린", "업무", "사무실", "점포")),
    (PropertyCategory.LAND, ("토지", "임야", "전", "답", "대지")),
]


def map_category(*texts: str | None) -> PropertyCategory:
    blob = " ".join(t for t in texts if t)
    for cat, keywords in _CATEGORY_KEYWORDS:
        if any(kw in blob for kw in keywords):
            return cat
    return PropertyCategory.ETC


# 온비드 진행상태 텍스트 → AuctionStatus
def map_status(*texts: str | None) -> AuctionStatus:
    blob = " ".join(t for t in texts if t)
    if any(k in blob for k in ("낙찰", "매각", "성공")):
        return AuctionStatus.SOLD
    if any(k in blob for k in ("유찰",)):
        return AuctionStatus.FAILED
    if any(k in blob for k in ("취하", "변경", "정지", "취소")):
        return AuctionStatus.CANCELLED
    if any(k in blob for k in ("진행", "공고",)):
        return AuctionStatus.ONGOING
    return AuctionStatus.SCHEDULED


def parse_int(s: str | None) -> int | None:
    if not s:
        return None
    digits = "".join(c for c in s if c.isdigit())
    return int(digits) if digits else None


def parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    s = s.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y%m%d%H%M%S", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def split_region(address: str | None) -> tuple[str | None, str | None]:
    """간단한 시도/시군구 분리. 정밀화는 추후."""
    if not address:
        return (None, None)
    parts = address.split()
    sido = parts[0] if len(parts) >= 1 else None
    sigungu = parts[1] if len(parts) >= 2 else None
    return (sido, sigungu)


def normalize_item(raw: dict[str, Any]) -> AuctionUpsertItem | None:
    """온비드 응답 한 건 → AuctionUpsertItem. external_id 또는 주소 없으면 None."""
    external_id = (
        raw.get("CLTR_NO") or raw.get("cltrNo") or raw.get("PLNM_NO") or ""
    ).strip()
    if not external_id:
        return None

    address = (
        raw.get("LDNM_ADRS")
        or raw.get("ldnmAdrs")
        or raw.get("RDNM_ADRS")
        or raw.get("rdnmAdrs")
        or raw.get("ADRS")
        or ""
    ).strip()
    if not address:
        return None

    title = (raw.get("CLTR_NM") or raw.get("cltrNm") or "").strip() or None
    case_number = (
        raw.get("PLNM_NO") or raw.get("PBCT_NO") or raw.get("plnmNo") or ""
    ).strip() or None
    category_text = (raw.get("CTGR_FULL_NM") or raw.get("CTGR_NM") or "").strip()
    status_text = (raw.get("PBCT_STAT") or raw.get("CLTR_STAT_NM") or "").strip()
    agency_name = (raw.get("INS_NM") or raw.get("DPSL_INS_NM") or "").strip() or None

    sido, sigungu = split_region(address)

    return AuctionUpsertItem(
        source=AuctionSource.ONBID,
        external_id=external_id,
        case_number=case_number,
        category=map_category(category_text, title),
        status=map_status(status_text),
        title=title,
        address=address,
        region_sido=sido,
        region_sigungu=sigungu,
        appraisal_price=parse_int(
            raw.get("APSL_AMT") or raw.get("APPR_PRC")
        ),
        minimum_bid_price=parse_int(
            raw.get("MIN_BID_PRC") or raw.get("MIN_BID_AMT")
        ),
        bid_deposit=parse_int(raw.get("BID_DPST")),
        auction_date=parse_dt(
            raw.get("BID_BEGIN_DTM") or raw.get("BID_BEGN_DT") or raw.get("PBCT_BEGN_DTM")
        ),
        agency_name=agency_name,
        description=(raw.get("CLTR_RM") or raw.get("BID_RM") or "").strip() or None,
        raw=raw,
    )


@dataclass(slots=True)
class IngestStats:
    fetched: int = 0
    normalized: int = 0
    geocoded: int = 0
    inserted: int = 0
    updated: int = 0
    pages: int = 0


# 전국 카테고리 풀 - run_full에서 순회. 일 1,000건 한도 고려해 부동산 우선.
DEFAULT_CATEGORY_CODES = (
    OnbidTopCategory.REAL_ESTATE,
    OnbidTopCategory.MOVABLE,
    OnbidTopCategory.RIGHTS,
    OnbidTopCategory.ETC,
)


class OnbidIngestService:
    def __init__(
        self,
        client: OnbidClient,
        geocoder: KakaoGeocoder,
        repo: AuctionRepository,
    ) -> None:
        self._client = client
        self._geocoder = geocoder
        self._repo = repo

    async def run_one(
        self,
        *,
        ctgr_hirk_id: str | None = None,
        max_pages: int = 1,
        num_of_rows: int = 100,
    ) -> IngestStats:
        """단일 카테고리 일부 페이지만 적재 (수동 트리거용)."""
        return await self._run(
            ctgr_hirk_id=ctgr_hirk_id,
            max_pages=max_pages,
            num_of_rows=num_of_rows,
        )

    async def run_full(
        self,
        *,
        max_pages_per_category: int = 50,
        num_of_rows: int = 200,
    ) -> IngestStats:
        """모든 카테고리를 순회 (새벽 배치용)."""
        total = IngestStats()
        for code in DEFAULT_CATEGORY_CODES:
            try:
                s = await self._run(
                    ctgr_hirk_id=code,
                    max_pages=max_pages_per_category,
                    num_of_rows=num_of_rows,
                )
            except OnbidQuotaExceeded as e:
                logger.warning("Quota exceeded — stopping run_full: %s", e)
                break
            total.fetched += s.fetched
            total.normalized += s.normalized
            total.geocoded += s.geocoded
            total.inserted += s.inserted
            total.updated += s.updated
            total.pages += s.pages
        return total

    async def _run(
        self,
        *,
        ctgr_hirk_id: str | None,
        max_pages: int,
        num_of_rows: int,
    ) -> IngestStats:
        stats = IngestStats()
        async for page in self._client.iter_all_pages(
            ctgr_hirk_id=ctgr_hirk_id,
            num_of_rows=num_of_rows,
            max_pages=max_pages,
        ):
            stats.pages += 1
            stats.fetched += len(page.items)
            normalized: list[AuctionUpsertItem] = []
            for raw in page.items:
                item = normalize_item(raw)
                if item is None:
                    continue
                normalized.append(item)
            stats.normalized += len(normalized)

            for item in normalized:
                lng, lat = await self._geocoder.lookup(item.address)
                if lng is not None and lat is not None:
                    item.lng = lng
                    item.lat = lat
                    stats.geocoded += 1

            if normalized:
                ins, upd = await self._repo.upsert_many(normalized)
                stats.inserted += ins
                stats.updated += upd
                logger.info(
                    "ingest page=%d ctgr=%s fetched=%d normalized=%d "
                    "geocoded=%d inserted=%d updated=%d",
                    page.page_no, ctgr_hirk_id,
                    len(page.items), len(normalized),
                    stats.geocoded, ins, upd,
                )
        return stats
