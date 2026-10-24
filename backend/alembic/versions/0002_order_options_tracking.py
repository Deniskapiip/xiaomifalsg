"""order options and tracking

Revision ID: 0002
Revises: 0001
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0002'
down_revision: Union[str, None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('orders', schema=None) as batch_op:
        batch_op.add_column(sa.Column('insurance_enabled', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('packing_enabled', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('photo_report_enabled', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('insurance_rub', sa.BigInteger(), nullable=False, server_default=sa.text('0')))
        batch_op.add_column(sa.Column('packing_rub', sa.BigInteger(), nullable=False, server_default=sa.text('0')))
        batch_op.add_column(sa.Column('photo_report_rub', sa.BigInteger(), nullable=False, server_default=sa.text('0')))
        batch_op.add_column(sa.Column('extras_total_rub', sa.BigInteger(), nullable=False, server_default=sa.text('0')))
        batch_op.add_column(sa.Column('total_with_extras_rub', sa.BigInteger(), nullable=False, server_default=sa.text('0')))
        batch_op.add_column(sa.Column('track_number', sa.String(length=64), nullable=True))
        batch_op.create_index('ix_orders_track_number', ['track_number'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('orders', schema=None) as batch_op:
        batch_op.drop_index('ix_orders_track_number')
        batch_op.drop_column('track_number')
        batch_op.drop_column('total_with_extras_rub')
        batch_op.drop_column('extras_total_rub')
        batch_op.drop_column('photo_report_rub')
        batch_op.drop_column('packing_rub')
        batch_op.drop_column('insurance_rub')
        batch_op.drop_column('photo_report_enabled')
        batch_op.drop_column('packing_enabled')
        batch_op.drop_column('insurance_enabled')
