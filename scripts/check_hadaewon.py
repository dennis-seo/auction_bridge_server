"""ad-hoc: 경기도 성남시 중원구 하대원동 아파트 공매 물건 수 조회 (Onbid getRlstCltrList2)."""
from __future__ import annotations

import asyncio
import os
import sys
from collections import Counter

from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.infrastructure.external.onbid_client import (
    OnbidAssetService,
    OnbidClient,
    PrptDivCd,
)


def is_apartment(item: dict) -> bool:
    blob = " ".join(
        str(item.get(k) or "")
        for k in (
            "cltrUsgSclsCtgrNm",
            "cltrUsgMclsCtgrNm",
            "cltrUsgLclsCtgrNm",
            "cltrNm",
            "dtlCltrNm",
        )
    )
    return "아파트" in blob


async def main() -> None:
    load_dotenv(".env.production")
    if not os.getenv("ONBID_SERVICE_KEY"):
        load_dotenv(".env")
    key = os.getenv("ONBID_SERVICE_KEY", "").strip()
    if not key:
        print("ONBID_SERVICE_KEY not set", file=sys.stderr)
        sys.exit(1)
    client = OnbidClient(service_key=key)

    addr_filter = {
        "lctnSdnm": "경기도",
        "lctnSggnm": "성남시 중원구",
        "lctnEmdNm": "하대원동",
    }

    all_items: list[dict] = []
    per_prpt: dict[str, int] = {}
    for code in PrptDivCd.DEFAULT_INGEST:
        page_no = 1
        fetched = 0
        while True:
            page = await client.list_assets(
                OnbidAssetService.REALTY,
                prpt_div_cd=code,
                page_no=page_no,
                num_of_rows=100,
                extra=addr_filter,
            )
            all_items.extend(page.items)
            fetched += len(page.items)
            if not page.has_more:
                break
            page_no += 1
        per_prpt[code] = fetched

    apt_items = [it for it in all_items if is_apartment(it)]

    print(f"총 부동산 hits (하대원동, 전 prptDivCd): {len(all_items)}")
    print(f"  per prptDivCd: {per_prpt}")
    print(f"\n그 중 '아파트' 매칭: {len(apt_items)}")

    cats = Counter(it.get("cltrUsgSclsCtgrNm") or it.get("cltrUsgMclsCtgrNm") for it in all_items)
    print(f"\n용도 분포 (전체): {dict(cats)}")

    for i, it in enumerate(apt_items, 1):
        print(
            f"\n[{i}] cltrMngNo={it.get('cltrMngNo')} pbctCdtnNo={it.get('pbctCdtnNo')}"
        )
        print(f"    cltrNm        = {it.get('cltrNm')}")
        print(f"    usgScls       = {it.get('cltrUsgSclsCtgrNm')}")
        print(f"    prptDivNm     = {it.get('prptDivNm')}")
        print(f"    pbctStatNm    = {it.get('pbctStatNm')}")
        print(f"    zadrNm        = {it.get('zadrNm')}")
        print(f"    cltrRadr      = {it.get('cltrRadr')}")
        print(f"    apslEvlAmt    = {it.get('apslEvlAmt')}")
        print(f"    bidEndDt      = {it.get('scrnGrpEndDtm') or it.get('bidEndDt')}")


if __name__ == "__main__":
    asyncio.run(main())
