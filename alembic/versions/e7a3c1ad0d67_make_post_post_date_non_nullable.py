"""Make Post.post_date non-nullable

Revision ID: e7a3c1ad0d67
Revises: 9f383fc1e17e
Create Date: 2023-06-05 09:09:55.049984

"""
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "e7a3c1ad0d67"
down_revision = "9f383fc1e17e"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        "post",
        "post_date",
        existing_type=postgresql.TIMESTAMP(timezone=True),
        nullable=False,
    )


def downgrade():
    op.alter_column(
        "post",
        "post_date",
        existing_type=postgresql.TIMESTAMP(timezone=True),
        nullable=True,
    )
