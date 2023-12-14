"""Add token column to User table

Revision ID: 0a280a2428ad
Revises: e7a3c1ad0d67
Create Date: 2023-12-15 03:55:30.532565

"""
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0a280a2428ad"
down_revision = "e7a3c1ad0d67"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("user", sa.Column("token", sa.String(length=32), nullable=True))


def downgrade():
    op.drop_column("user", "token")
