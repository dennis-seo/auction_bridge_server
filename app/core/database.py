import logging
from collections.abc import AsyncIterator
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# 시크릿을 노출하지 않으면서 Cloud Run에서 실제 어떤 endpoint를 보고 있는지 확인.
_p = urlparse(settings.DATABASE_URL)
logger.warning(
    "DB engine config — scheme=%s user=%s host=%s port=%s db=%s",
    _p.scheme, _p.username, _p.hostname, _p.port, (_p.path or "/").lstrip("/"),
)


def _is_supabase_pooler(url: str) -> bool:
    """Supabase Transaction/Session Pooler 호스트 여부.

    URL parse로 hostname suffix를 정확히 검사 — substring 매칭은 ``foo.pooler.supabase.com.evil.com`` 같은
    악성 호스트나 path/query에 우연히 들어간 문자열에 오탐할 수 있어 회피.
    """
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    return host.endswith(".pooler.supabase.com") or host == "pooler.supabase.com"


_is_pooler = _is_supabase_pooler(settings.DATABASE_URL)
_connect_args: dict = {}
if _is_pooler:
    # Supabase Transaction Pooler는 PREPARE를 캐시 못 함 → asyncpg statement cache 끔.
    _connect_args = {"statement_cache_size": 0, "prepared_statement_cache_size": 0}

engine = create_async_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    echo=settings.APP_DEBUG,
    connect_args=_connect_args,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db_session() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        yield session
