"""tariff price on request

Revision ID: 0007
Revises: 0006
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0007'
down_revision: Union[str, None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('tariffs') as batch:
        batch.add_column(sa.Column('price_on_request', sa.Boolean(), nullable=False,
                                   server_default=sa.false()))
    # Существующие тарифы с нулевой ценой — это «цена по запросу».
    op.execute('UPDATE tariffs SET price_on_request = 1 WHERE price_per_kg = 0')


def downgrade() -> None:
    with op.batch_alter_table('tariffs') as batch:
        batch.drop_column('price_on_request')
