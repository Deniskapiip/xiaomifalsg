"""tariff currency, per-tariff insurance, packing boxes

Revision ID: 0003
Revises: 0002
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import app.db_types


revision: str = '0003'
down_revision: Union[str, None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('tariffs', schema=None) as batch_op:
        batch_op.alter_column('price_per_kg_rub', new_column_name='price_per_kg')
        batch_op.add_column(sa.Column('price_currency', sa.String(length=3), nullable=False, server_default=sa.text("'rub'")))
        batch_op.add_column(sa.Column('insurance_available', sa.Boolean(), nullable=False, server_default=sa.false()))

    tariffs = sa.table('tariffs', sa.column('name', sa.String), sa.column('insurance_available', sa.Boolean))
    op.execute(tariffs.update().where(tariffs.c.name == 'Китай - Благовещенск').values(insurance_available=sa.true()))

    with op.batch_alter_table('orders', schema=None) as batch_op:
        batch_op.add_column(sa.Column('boxes', sa.Integer(), nullable=False, server_default=sa.text('1')))
        batch_op.add_column(sa.Column('tariff_price_currency', sa.String(length=3), nullable=False, server_default=sa.text("'rub'")))
        batch_op.add_column(sa.Column('tariff_price_value', app.db_types.ExactDecimal(12, 2), nullable=False, server_default=sa.text('0')))

    op.execute('UPDATE orders SET tariff_price_value = tariff_price_per_kg')


def downgrade() -> None:
    with op.batch_alter_table('orders', schema=None) as batch_op:
        batch_op.drop_column('tariff_price_value')
        batch_op.drop_column('tariff_price_currency')
        batch_op.drop_column('boxes')

    with op.batch_alter_table('tariffs', schema=None) as batch_op:
        batch_op.drop_column('insurance_available')
        batch_op.drop_column('price_currency')
        batch_op.alter_column('price_per_kg', new_column_name='price_per_kg_rub')
