"""auctions.pbanc_mng_no VARCHAR(40) 컬럼 추가

getPbancCltrInf2(공고상세 물건정보) 호출용 캐시. 공식 OpenAPI의
getRlstCltrList2가 임박 회차(D-7 이내)를 가리는 정책 때문에, 공고 단위로
모든 회차를 보강하려면 pbancMngNo가 필요한데 detail 응답에는 없음.
한 번 getPbancList2로 매핑을 해결하면 재호출을 피하기 위해 컬럼화한다.

Revision ID: 0003_auctions_pbanc_mng_no
Revises: 0002_auctions_bid_info
Create Date: 2026-05-12
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0003_auctions_pbanc_mng_no"
down_revision: Union[str, Sequence[str], None] = "0002_auctions_bid_info"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "auctions",
        sa.Column("pbanc_mng_no", sa.String(length=40), nullable=True),
    )
    op.create_index(
        "idx_auctions_pbanc_mng_no",
        "auctions",
        ["pbanc_mng_no"],
    )


def downgrade() -> None:
    op.drop_index("idx_auctions_pbanc_mng_no", table_name="auctions")
    op.drop_column("auctions", "pbanc_mng_no")
