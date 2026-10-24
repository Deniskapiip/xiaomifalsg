"""order tracking fields (DobroPost statuses for orders)

Revision ID: 0006
Revises: 0005
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0006'
down_revision: Union[str, None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('orders') as batch:
        batch.add_column(sa.Column('tracking_status_text', sa.String(length=200), nullable=False,
                                   server_default=sa.text("''")))
        batch.add_column(sa.Column('tracking_checked_at', sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column('tracking_next_check_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index('ix_orders_tracking_next_check', 'orders', ['tracking_next_check_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_orders_tracking_next_check', table_name='orders')
    with op.batch_alter_table('orders') as batch:
        batch.drop_column('tracking_next_check_at')
        batch.drop_column('tracking_checked_at')
        batch.drop_column('tracking_status_text')
