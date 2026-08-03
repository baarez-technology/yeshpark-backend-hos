"""Add DNM (Do Not Move) fields to bookings table

Revision ID: a1b2c3d4e5f6
Revises: 5175cfb06aed
Create Date: 2026-02-22

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = 'a1b2c3d4e5f6'
down_revision = '5175cfb06aed'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('bookings', sa.Column('do_not_move', sa.Boolean(), nullable=True, server_default='false'))
    op.add_column('bookings', sa.Column('dnm_set_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True))
    op.add_column('bookings', sa.Column('dnm_set_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('bookings', 'dnm_set_at')
    op.drop_column('bookings', 'dnm_set_by')
    op.drop_column('bookings', 'do_not_move')
