"""부동산 목록 검색(GET /api/v1/realty)용 인덱스 추가

가격/유찰/신건 정렬·필터가 자주 쓰는 컬럼과, deadline 정렬의 주 경로인
(asset_type, status, bid_end_at) 복합 인덱스. region/면적 인덱스는
baseline(db/schema.sql)에 이미 존재.

Revision ID: 0004_realty_list_indexes
Revises: 0003_auctions_pbanc_mng_no
Create Date: 2026-07-16
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0004_realty_list_indexes"
down_revision: Union[str, Sequence[str], None] = "0003_auctions_pbanc_mng_no"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "idx_auctions_min_bid_price",
        "auctions",
        ["min_bid_price"],
    )
    op.create_index(
        "idx_auctions_failed_count",
        "auctions",
        ["failed_count"],
    )
    op.create_index(
        "idx_auctions_created_at",
        "auctions",
        [sa.text("created_at DESC")],
    )
    op.create_index(
        "idx_auctions_asset_status_end",
        "auctions",
        ["asset_type", "status", "bid_end_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_auctions_asset_status_end", table_name="auctions")
    op.drop_index("idx_auctions_created_at", table_name="auctions")
    op.drop_index("idx_auctions_failed_count", table_name="auctions")
    op.drop_index("idx_auctions_min_bid_price", table_name="auctions")
