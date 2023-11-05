"""Add indexes to Artwork.aid and Post.post_id

Revision ID: 9f383fc1e17e
Revises: 983997dbb0e4
Create Date: 2022-12-17 23:48:22.788332

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "9f383fc1e17e"
down_revision = "983997dbb0e4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(op.f("ix_artwork_aid"), "artwork", ["aid"], unique=False)
    op.create_index(op.f("ix_post_post_id"), "post", ["post_id"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_post_post_id"), table_name="post")
    op.drop_index(op.f("ix_artwork_aid"), table_name="artwork")
