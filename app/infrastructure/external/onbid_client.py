"""차세대 온비드 OpenAPI 클라이언트 (data.go.kr B010003).

신청 완료된 10개 서비스 중 본 클라이언트가 다루는 것:
  - 부동산 물건목록  : OnbidRlstListSrvc2  / getRlstCltrList2
  - 동산   물건목록  : OnbidMvastListSrvc2 / getMvastCltrList2
  - 차량   물건목록  : OnbidCarListSrvc2   / getCarCltrList2
  - 부동산 물건상세  : OnbidRlstDtlSrvc2   / getRlstDtlInf2
  - 동산   물건상세  : OnbidMvastDtlSrvc2  / getMvastDtlInf2
  - 물건상세 입찰정보: OnbidCltrBidDtlSrvc2/ getCltrBidInf2
  - 입찰결과목록     : OnbidCltrBidRsltListSrvc2/ getCltrBidRsltList2
  - 입찰결과상세     : OnbidCltrBidRsltDtlSrvc2 / getCltrBidRsltDtl2

응답은 JSON으로 강제(`resultType=json`).
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

import httpx

logger = logging.getLogger(__name__)


ONBID_BASE_URL = "https://apis.data.go.kr/B010003"


class OnbidAssetService(str, Enum):
    """asset_type → (서비스 path, operation) 매핑용 enum."""
    REALTY = "realty"
    MOVABLE = "movable"
    VEHICLE = "vehicle"


# 재산유형코드(prptDivCd)
class PrptDivCd:
    PB_AUCTION = "0007"      # 압류재산
    STATE = "0010"           # 국유재산
    OTHER_GENERAL = "0005"   # 기타일반재산
    UNUSED = "0004"          # 불용품
    PUBLIC = "0002"          # 공유재산
    DELEGATED = "0003"       # 수탁(?)
    BANKRUPTCY = "0013"      # 파산재산

    DEFAULT_INGEST = ("0007", "0010", "0005", "0004", "0002", "0003", "0013")


_LIST_PATHS: dict[OnbidAssetService, tuple[str, str]] = {
    OnbidAssetService.REALTY:  ("OnbidRlstListSrvc2",  "getRlstCltrList2"),
    OnbidAssetService.MOVABLE: ("OnbidMvastListSrvc2", "getMvastCltrList2"),
    OnbidAssetService.VEHICLE: ("OnbidCarListSrvc2",   "getCarCltrList2"),
}


# 입찰결과목록(#8) 호출 시 사용하는 cltrTypeCd (물건유형코드 — 목록조회의 prptDivCd와 별개)
#   0001=부동산, 0002=자동차, 0003=동산
CLTR_TYPE_CD: dict[OnbidAssetService, str] = {
    OnbidAssetService.REALTY:  "0001",
    OnbidAssetService.VEHICLE: "0002",
    OnbidAssetService.MOVABLE: "0003",
}


@dataclass(slots=True)
class OnbidPage:
    items: list[dict[str, Any]]
    total_count: int
    page_no: int
    num_of_rows: int

    @property
    def has_more(self) -> bool:
        return self.page_no * self.num_of_rows < self.total_count


class OnbidAPIError(RuntimeError):
    pass


class OnbidQuotaExceeded(OnbidAPIError):
    pass


class OnbidClient:
    """온비드 차세대 OpenAPI 비동기 클라이언트."""

    def __init__(
        self,
        service_key: str,
        base_url: str = ONBID_BASE_URL,
        timeout: float = 20.0,
        page_sleep: float = 0.3,
    ) -> None:
        if not service_key:
            raise ValueError(
                "ONBID_SERVICE_KEY is empty. data.go.kr 활용신청 후 발급된 키를 .env에 설정하세요."
            )
        self._service_key = service_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._page_sleep = page_sleep

    # ---------- 목록 ----------
    async def list_assets(
        self,
        asset: OnbidAssetService,
        *,
        prpt_div_cd: str | tuple[str, ...] = PrptDivCd.DEFAULT_INGEST,
        pvct_trgt_yn: str = "N",
        page_no: int = 1,
        num_of_rows: int = 100,
        extra: dict[str, Any] | None = None,
    ) -> OnbidPage:
        """재산유형별 물건목록 조회.

        prptDivCd, pvctTrgtYn은 차세대 API에서 둘 다 필수.
        prpt_div_cd는 단일/튜플 모두 지원 (튜플이면 쉼표 join).
        """
        svc, op = _LIST_PATHS[asset]
        params: dict[str, Any] = {
            "serviceKey": self._service_key,
            "pageNo": page_no,
            "numOfRows": num_of_rows,
            "resultType": "json",
            "prptDivCd": _join_codes(prpt_div_cd),
            "pvctTrgtYn": pvct_trgt_yn,
        }
        if extra:
            params.update({k: v for k, v in extra.items() if v is not None})

        url = f"{self._base_url}/{svc}/{op}"
        return await self._request_list(url, params, page_no=page_no, num_of_rows=num_of_rows)

    async def iter_assets(
        self,
        asset: OnbidAssetService,
        *,
        prpt_div_cd: str | tuple[str, ...] = PrptDivCd.DEFAULT_INGEST,
        pvct_trgt_yn: str = "N",
        num_of_rows: int = 100,
        max_pages: int | None = None,
        extra: dict[str, Any] | None = None,
    ):
        """모든 페이지 yield. 일 1000건 한도 고려해 호출자가 max_pages로 제어."""
        page_no = 1
        while True:
            page = await self.list_assets(
                asset,
                prpt_div_cd=prpt_div_cd,
                pvct_trgt_yn=pvct_trgt_yn,
                page_no=page_no,
                num_of_rows=num_of_rows,
                extra=extra,
            )
            yield page
            if not page.has_more:
                break
            if max_pages is not None and page_no >= max_pages:
                break
            page_no += 1
            await asyncio.sleep(self._page_sleep)

    # ---------- 상세 ----------
    async def get_realty_detail(
        self, *, cltr_mng_no: str, pbct_cdtn_no: int | str
    ) -> dict[str, Any]:
        """부동산 물건상세."""
        url = f"{self._base_url}/OnbidRlstDtlSrvc2/getRlstDtlInf2"
        params = {
            "serviceKey": self._service_key,
            "resultType": "json",
            "cltrMngNo": cltr_mng_no,
            "pbctCdtnNo": str(pbct_cdtn_no),
        }
        return await self._request_single(url, params)

    async def get_movable_detail(
        self, *, cltr_mng_no: str, pbct_cdtn_no: int | str
    ) -> dict[str, Any]:
        """동산 물건상세 (#5). potoUrlList[].urlAdr 구조는 부동산과 동일."""
        url = f"{self._base_url}/OnbidMvastDtlSrvc2/getMvastDtlInf2"
        params = {
            "serviceKey": self._service_key,
            "resultType": "json",
            "cltrMngNo": cltr_mng_no,
            "pbctCdtnNo": str(pbct_cdtn_no),
        }
        return await self._request_single(url, params)

    async def get_bid_info(
        self, *, cltr_mng_no: str, pbct_cdtn_no: int | str
    ) -> dict[str, Any]:
        """물건상세 입찰정보."""
        url = f"{self._base_url}/OnbidCltrBidDtlSrvc2/getCltrBidInf2"
        params = {
            "serviceKey": self._service_key,
            "resultType": "json",
            "cltrMngNo": cltr_mng_no,
            "pbctCdtnNo": str(pbct_cdtn_no),
        }
        return await self._request_single(url, params)

    # ---------- 입찰결과 ----------
    async def list_bid_results(
        self,
        *,
        cltr_type_cd: str,
        prpt_div_cd: str | tuple[str, ...] = PrptDivCd.DEFAULT_INGEST,
        opbd_dt_start: str,
        opbd_dt_end: str,
        page_no: int = 1,
        num_of_rows: int = 100,
    ) -> OnbidPage:
        """물건 입찰결과 목록 (#8) — 개찰일자 범위 + 물건유형 + 재산유형 필수."""
        url = f"{self._base_url}/OnbidCltrBidRsltListSrvc2/getCltrBidRsltList2"
        params = {
            "serviceKey": self._service_key,
            "resultType": "json",
            "pageNo": page_no,
            "numOfRows": num_of_rows,
            "cltrTypeCd": cltr_type_cd,
            "prptDivCd": _join_codes(prpt_div_cd),
            "opbdDtStart": opbd_dt_start,
            "opbdDtEnd": opbd_dt_end,
        }
        return await self._request_list(url, params, page_no=page_no, num_of_rows=num_of_rows)

    async def get_bid_result_detail(
        self, *, cltr_mng_no: str, pbct_cdtn_no: int | str
    ) -> dict[str, Any]:
        """물건 입찰결과 상세 (#9)."""
        url = f"{self._base_url}/OnbidCltrBidRsltDtlSrvc2/getCltrBidRsltDtl2"
        params = {
            "serviceKey": self._service_key,
            "resultType": "json",
            "cltrMngNo": cltr_mng_no,
            "pbctCdtnNo": str(pbct_cdtn_no),
        }
        return await self._request_single(url, params)

    # ---------- internals ----------
    async def _request_list(
        self, url: str, params: dict[str, Any], *, page_no: int, num_of_rows: int
    ) -> OnbidPage:
        data = await self._http_get_json(url, params)
        body = _navigate_body(data)
        items_block = body.get("items") or {}
        items_raw = items_block.get("item") if isinstance(items_block, dict) else items_block
        items = _normalize_items(items_raw)
        total_count = int(body.get("totalCount") or 0)
        return OnbidPage(
            items=items,
            total_count=total_count,
            page_no=page_no,
            num_of_rows=num_of_rows,
        )

    async def _request_single(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        data = await self._http_get_json(url, params)
        body = _navigate_body(data)
        items_block = body.get("items") or {}
        items_raw = items_block.get("item") if isinstance(items_block, dict) else items_block
        items = _normalize_items(items_raw)
        return items[0] if items else {}

    async def _http_get_json(
        self, url: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(url, params=params)
        resp.raise_for_status()

        try:
            data = resp.json()
        except ValueError as e:
            raise OnbidAPIError(f"non-JSON response: {resp.text[:300]}") from e

        # 표준 응답 헤더 검사
        header = _extract_header(data)
        code = (header.get("resultCode") or "").strip()
        msg = (header.get("resultMsg") or "").strip()
        if code and code != "00":
            if code in ("22", "30", "31", "32", "33") or "LIMIT" in msg.upper() or "QUOTA" in msg.upper():
                raise OnbidQuotaExceeded(f"Onbid API quota/auth: code={code} msg={msg}")
            raise OnbidAPIError(f"Onbid API error: code={code} msg={msg}")
        return data


# =====================================================================
# helpers
# =====================================================================
def _join_codes(v: str | tuple[str, ...] | list[str]) -> str:
    if isinstance(v, str):
        return v
    return ",".join(v)


def _navigate_body(data: dict[str, Any]) -> dict[str, Any]:
    """공공데이터포털 표준 응답 구조: {response: {header, body}} 또는 평면."""
    if not isinstance(data, dict):
        return {}
    if "response" in data:
        resp = data["response"] or {}
        return resp.get("body") or {}
    return data.get("body") or data


def _extract_header(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    if "response" in data and isinstance(data["response"], dict):
        return data["response"].get("header") or {}
    return data.get("header") or {}


def _normalize_items(items_raw: Any) -> list[dict[str, Any]]:
    """item이 단일 dict이거나 리스트일 수 있고, None일 수도 있음."""
    if items_raw is None:
        return []
    if isinstance(items_raw, list):
        return [i for i in items_raw if isinstance(i, dict)]
    if isinstance(items_raw, dict):
        return [items_raw]
    return []


# 부동산 상세 응답의 사진 URL 추출 (potoUrlList[].urlAdr).
# 차세대 v2 응답의 `urlAdr` 키를 1순위로 한다.
_PHOTO_URL_KEYS = ("urlAdr", "potoUrl", "imgUrl", "photoUrl")


def extract_image_urls(detail: dict[str, Any]) -> list[str]:
    """차세대 부동산 상세 응답에서 사진 URL 리스트만 뽑아낸다.

    응답에 `potoUrlList`가 list-of-dict, 단일 dict, 또는 None일 수 있다.
    """
    if not isinstance(detail, dict):
        return []
    block = detail.get("potoUrlList")
    if block is None:
        return []
    items = block if isinstance(block, list) else [block]
    urls: list[str] = []
    for el in items:
        if isinstance(el, dict):
            for key in _PHOTO_URL_KEYS:
                v = el.get(key)
                if isinstance(v, str) and v.strip():
                    urls.append(v.strip())
                    break
        elif isinstance(el, str) and el.strip():
            urls.append(el.strip())
    return urls


# ---------- dev script ----------
async def _main() -> None:
    """python -m app.infrastructure.external.onbid_client 로 sanity test."""
    import os
    import sys

    from dotenv import load_dotenv

    load_dotenv()
    key = os.getenv("ONBID_SERVICE_KEY", "").strip()
    if not key:
        print("ONBID_SERVICE_KEY is not set in .env", file=sys.stderr)
        sys.exit(1)

    client = OnbidClient(service_key=key)
    for asset in OnbidAssetService:
        print(f"\n=== {asset.value} ===")
        try:
            page = await client.list_assets(asset, num_of_rows=3, page_no=1)
        except OnbidAPIError as e:
            print(f"  ERROR: {e}", file=sys.stderr)
            continue
        print(f"  totalCount={page.total_count}, sample={len(page.items)}")
        for i, it in enumerate(page.items, 1):
            keys_with_val = sorted(k for k, v in it.items() if v not in (None, ""))
            print(f"  -- item #{i} --")
            print(f"     non-empty keys ({len(keys_with_val)}): {keys_with_val}")
            for k in ("cltrMngNo", "pbctCdtnNo", "onbidCltrno", "onbidCltrNm"):
                if k in it:
                    print(f"     {k} = {it[k]}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_main())
