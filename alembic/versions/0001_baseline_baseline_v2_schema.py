"""baseline_v2_schema

차세대 온비드 v2 스키마(asset_type 분리 + bid_results) 도입 시점의 baseline.
이 시점까지의 DDL은 Supabase MCP `apply_migration`으로 직접 적용했으며,
이 revision은 그 상태를 alembic 버전 히스토리에 등록하기 위한 빈 baseline이다.

이후 변경은 모두 `alembic revision --autogenerate`로 추가.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-05-06
"""
from typing import Sequence, Union


revision: str = "0001_baseline"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """No-op — DDL은 db/schema.sql / Supabase 마이그레이션 히스토리에 이미 적용됨."""
    pass


def downgrade() -> None:
    """Baseline 이전 상태는 정의되지 않음."""
    pass
