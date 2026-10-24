"""tracking links (external carrier track numbers)

Revision ID: 0005
Revises: 0004
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0005'
down_revision: Union[str, None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'tracking_links',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('provider', sa.String(length=20), nullable=False, server_default=sa.text("'dobropost'")),
        sa.Column('track_number', sa.String(length=64), nullable=False),
        sa.Column('status_text', sa.String(length=200), nullable=False, server_default=sa.text("''")),
        sa.Column('ok', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('last_checked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('next_check_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'provider', 'track_number', name='unique_tracking_link'),
    )
    op.create_index('ix_tracking_links_user_id', 'tracking_links', ['user_id'], unique=False)
    op.create_index('ix_tracking_links_due', 'tracking_links', ['next_check_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_tracking_links_due', table_name='tracking_links')
    op.drop_index('ix_tracking_links_user_id', table_name='tracking_links')
    op.drop_table('tracking_links')
