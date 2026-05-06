"""Cloud Scheduler가 트리거하는 cron 엔드포인트.

Cloud Scheduler는 OIDC ID 토큰을 Authorization: Bearer 헤더로 보낸다.
구글 공개키로 토큰을 검증하고, audience와 발급자(email) 화이트리스트가
일치할 때만 작업을 실행한다.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Header, HTTPException, status
from google.auth.transport import requests as g_requests
from google.oauth2 import id_token

from app.core.config import get_settings
from app.services.scheduler import run_daily_onbid_ingest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal/cron", tags=["cron"], include_in_schema=False)


def _verify_oidc(authorization: str | None) -> None:
    settings = get_settings()
    expected_email = settings.CRON_SERVICE_ACCOUNT_EMAIL
    expected_aud = settings.CRON_AUDIENCE

    if not expected_email or not expected_aud:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="cron auth not configured",
        )
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing bearer")

    token = authorization.removeprefix("Bearer ").strip()
    try:
        info = id_token.verify_oauth2_token(
            token, g_requests.Request(), audience=expected_aud
        )
    except ValueError as e:
        logger.warning("OIDC verification failed: %s", e)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token")

    if info.get("email") != expected_email or not info.get("email_verified"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="email mismatch")


@router.post("/daily-ingest", summary="일 1회 온비드 ingest (Cloud Scheduler 호출)")
async def daily_ingest(authorization: str | None = Header(default=None)) -> dict:
    _verify_oidc(authorization)
    result = await run_daily_onbid_ingest()
    return {"ok": True, "result": result}
