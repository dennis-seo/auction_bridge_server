"""auctions.bid_info JSONB 컬럼 추가

#7 물건상세 입찰정보(getCltrBidInf2) 응답을 매물 1:1로 저장하기 위한 컬럼.
NOT NULL DEFAULT '{}'::jsonb 로 추가해 기존 row는 빈 객체로 채워진다.

Revision ID: 0002_auctions_bid_info
Revises: 0001_baseline
Create Date: 2026-05-12
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "0002_auctions_bid_info"
down_revision: Union[str, Sequence[str], None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "auctions",
        sa.Column(
            "bid_info",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("auctions", "bid_info")
