"""
공공데이터포털 - 한국자산관리공사 온비드 캠코공매물건 조회서비스 클라이언트.

DataID: 15000851 (https://www.data.go.kr/data/15000851/openapi.do)

응답은 기본 XML이며, 본 클라이언트는 정규화된 dict 리스트로 변환해 돌려준다.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any
from xml.etree import ElementTree as ET

import httpx

logger = logging.getLogger(__name__)


# 캠코공매물건 조회서비스 베이스 URL
ONBID_BASE_URL = (
    "https://apis.data.go.kr/1360000/OnbidPublicSaleInfoInquireSvc"
)

# 메이저 카테고리 코드 (CTGR_HIRK_ID, 상위 분류)
# 부동산: 10000, 동산: 20000, 권리/유가증권: 30000, 기타: 40000
class OnbidTopCategory:
    REAL_ESTATE = "10000"
    MOVABLE = "20000"
    RIGHTS = "30000"
    ETC = "40000"


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
    """온비드 캠코공매물건 클라이언트 (비동기)."""

    def __init__(
        self,
        service_key: str,
        base_url: str = ONBID_BASE_URL,
        timeout: float = 15.0,
        page_sleep: float = 0.3,
    ) -> None:
        if not service_key:
            raise ValueError(
                "ONBID_SERVICE_KEY is empty. "
                "data.go.kr 활용신청 후 발급된 키를 .env에 설정하세요."
            )
        self._service_key = service_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._page_sleep = page_sleep

    async def list_cltr(
        self,
        *,
        ctgr_hirk_id: str | None = None,
        sido: str | None = None,
        sgk: str | None = None,
        page_no: int = 1,
        num_of_rows: int = 100,
    ) -> OnbidPage:
        """캠코공매물건 목록 조회 (operation: getCltrMnsList).

        파라미터는 선택. 카테고리/지역 필터를 좁힐수록 응답이 작아짐.
        """
        params = {
            "serviceKey": self._service_key,
            "numOfRows": num_of_rows,
            "pageNo": page_no,
            "_type": "xml",  # 명시적으로 XML 요청 (기본도 XML)
        }
        if ctgr_hirk_id:
            params["CTGR_HIRK_ID"] = ctgr_hirk_id
        if sido:
            params["SIDO"] = sido
        if sgk:
            params["SGK"] = sgk

        url = f"{self._base_url}/getCltrMnsList"

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(url, params=params)
        resp.raise_for_status()

        return _parse_xml_response(resp.text, page_no=page_no, num_of_rows=num_of_rows)

    async def iter_all_pages(
        self,
        *,
        ctgr_hirk_id: str | None = None,
        sido: str | None = None,
        sgk: str | None = None,
        num_of_rows: int = 100,
        max_pages: int | None = None,
    ):
        """카테고리/지역 조합으로 모든 페이지를 yield. 페이지 간 sleep 포함."""
        page_no = 1
        while True:
            page = await self.list_cltr(
                ctgr_hirk_id=ctgr_hirk_id,
                sido=sido, sgk=sgk,
                page_no=page_no, num_of_rows=num_of_rows,
            )
            yield page
            if not page.has_more:
                break
            if max_pages is not None and page_no >= max_pages:
                break
            page_no += 1
            await asyncio.sleep(self._page_sleep)


def _parse_xml_response(
    xml_text: str, *, page_no: int, num_of_rows: int
) -> OnbidPage:
    """공공데이터포털 표준 응답 XML을 파싱."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise OnbidAPIError(f"XML parse failed: {e}\n{xml_text[:500]}") from e

    # 표준 헤더 검사 (resultCode / resultMsg)
    header = root.find(".//header")
    if header is not None:
        result_code = (header.findtext("resultCode") or "").strip()
        result_msg = (header.findtext("resultMsg") or "").strip()
        if result_code and result_code != "00":
            if "QUOTA" in result_msg.upper() or result_code in ("22", "30"):
                raise OnbidQuotaExceeded(
                    f"Onbid API quota/auth issue: code={result_code}, msg={result_msg}"
                )
            raise OnbidAPIError(
                f"Onbid API error: code={result_code}, msg={result_msg}"
            )

    # 일부 응답은 OpenAPI_ServiceResponse 형태로 SERVICE_KEY 오류를 알려줌
    if root.tag.endswith("OpenAPI_ServiceResponse"):
        err_msg = (
            root.findtext(".//returnAuthMsg")
            or root.findtext(".//errMsg")
            or root.findtext(".//returnReasonCode")
            or "unknown error"
        )
        if "LIMITED" in (err_msg or "").upper() or "QUOTA" in (err_msg or "").upper():
            raise OnbidQuotaExceeded(f"Onbid quota exceeded: {err_msg}")
        raise OnbidAPIError(f"Onbid service error: {err_msg}\n{xml_text[:500]}")

    # totalCount
    total_count = int((root.findtext(".//totalCount") or "0").strip() or 0)

    # items
    items: list[dict[str, Any]] = []
    for item_el in root.findall(".//items/item"):
        items.append({child.tag: (child.text or "").strip() for child in item_el})

    return OnbidPage(
        items=items,
        total_count=total_count,
        page_no=page_no,
        num_of_rows=num_of_rows,
    )


# ---------- dev script ----------
async def _main() -> None:
    """python -m app.infrastructure.external.onbid_client 로 호출 가능한 sanity test."""
    import os, sys
    from dotenv import load_dotenv

    load_dotenv()
    key = os.getenv("ONBID_SERVICE_KEY", "").strip()
    if not key:
        print("ONBID_SERVICE_KEY is not set in .env", file=sys.stderr)
        sys.exit(1)

    client = OnbidClient(service_key=key)
    page = await client.list_cltr(
        ctgr_hirk_id=OnbidTopCategory.REAL_ESTATE,
        page_no=1, num_of_rows=5,
    )
    print(f"totalCount: {page.total_count}, items: {len(page.items)}")
    for i, it in enumerate(page.items, 1):
        print(f"--- item #{i} ---")
        for k, v in it.items():
            print(f"  {k}: {v}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_main())
