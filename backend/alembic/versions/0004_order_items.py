"""order items (multi-item orders)

Revision ID: 0004
Revises: 0003
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import app.db_types


revision: str = '0004'
down_revision: Union[str, None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'order_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('order_id', sa.Integer(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('link', sa.String(length=2000), nullable=False),
        sa.Column('platform', sa.String(length=20), nullable=False),
        sa.Column('item_title', sa.String(length=200), nullable=False, server_default=sa.text("''")),
        sa.Column('price_cny', app.db_types.ExactDecimal(12, 2), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False, server_default=sa.text('1')),
        sa.Column('comment', sa.String(length=500), nullable=False, server_default=sa.text("''")),
        sa.ForeignKeyConstraint(['order_id'], ['orders.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint('quantity >= 1 AND quantity <= 999', name='order_item_quantity_bounds'),
    )
    op.create_index('ix_order_items_order_position', 'order_items', ['order_id', 'position'], unique=False)
    # Каждый существующий заказ становится заказом с одной позицией.
    op.execute(
        'INSERT INTO order_items (order_id, position, link, platform, item_title, price_cny, quantity, comment) '
        'SELECT id, 0, link, platform, item_title, price_cny, quantity, comment FROM orders'
    )


def downgrade() -> None:
    op.drop_index('ix_order_items_order_position', table_name='order_items')
    op.drop_table('order_items')
