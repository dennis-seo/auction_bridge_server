"""Kakao Local API - 주소 → 위경도 지오코딩."""
from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict

import httpx

logger = logging.getLogger(__name__)


KAKAO_LOCAL_BASE_URL = "https://dapi.kakao.com"
ADDRESS_SEARCH_PATH = "/v2/local/search/address.json"


class KakaoGeocoder:
    """주소 텍스트 → (lng, lat).

    - REST API 키가 없으면(빈 문자열) 항상 (None, None) 반환 → ingest는 graceful 진행.
    - in-memory LRU 캐시(주소 → (lng, lat)).
    """

    def __init__(
        self,
        rest_api_key: str,
        timeout: float = 5.0,
        cache_size: int = 5000,
    ) -> None:
        self._key = (rest_api_key or "").strip()
        self._timeout = timeout
        self._cache: OrderedDict[str, tuple[float | None, float | None]] = OrderedDict()
        self._cache_size = cache_size
        self._lock = asyncio.Lock()

    @property
    def enabled(self) -> bool:
        return bool(self._key)

    async def lookup(self, address: str) -> tuple[float | None, float | None]:
        """반환: (lng, lat). 키 없거나 실패하면 (None, None)."""
        if not self.enabled or not address:
            return (None, None)

        key = address.strip()
        async with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]

        coords = await self._call_api(key)

        async with self._lock:
            self._cache[key] = coords
            if len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)
        return coords

    async def _call_api(self, address: str) -> tuple[float | None, float | None]:
        headers = {"Authorization": f"KakaoAK {self._key}"}
        params = {"query": address}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(
                    f"{KAKAO_LOCAL_BASE_URL}{ADDRESS_SEARCH_PATH}",
                    headers=headers, params=params,
                )
        except httpx.HTTPError as e:
            logger.warning("Kakao geocoder HTTP error for %r: %s", address, e)
            return (None, None)

        if resp.status_code != 200:
            logger.warning(
                "Kakao geocoder non-200 (%d) for %r: %s",
                resp.status_code, address, resp.text[:200],
            )
            return (None, None)

        try:
            data = resp.json()
        except ValueError:
            logger.warning("Kakao geocoder non-JSON for %r", address)
            return (None, None)

        docs = data.get("documents") or []
        if not docs:
            return (None, None)

        first = docs[0]
        if not _is_parcel_level(first):
            # 행정구역 centroid 응답 거부 — 같은 동 매물이 한 점으로 뭉치는 것을 차단.
            logger.info(
                "Kakao geocoder returned region-level match for %r — skipping",
                address,
            )
            return (None, None)
        try:
            lng = float(first["x"])
            lat = float(first["y"])
        except (KeyError, TypeError, ValueError):
            return (None, None)
        return (lng, lat)


def _is_parcel_level(doc: dict) -> bool:
    """카카오 응답 1건이 동(洞) centroid가 아니라 실제 지번/도로명 좌표인지 판단.

    - address.address_type 가 "REGION" 이면 행정구역 centroid → 거부
    - address.main_address_no 가 있거나 road_address 가 존재하면 parcel 단위
    """
    addr = doc.get("address") or {}
    road = doc.get("road_address") or {}
    if road:
        return True
    addr_type = (addr.get("address_type") or "").strip().upper()
    if addr_type == "REGION":
        return False
    main_no = (addr.get("main_address_no") or "").strip()
    return bool(main_no and main_no != "0")
