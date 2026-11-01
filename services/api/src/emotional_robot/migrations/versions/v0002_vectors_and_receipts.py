"""Add rebuildable embedding data and replay receipts for the external deletion ledger."""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "0002_vectors_receipts"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "memory_embeddings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("memory_id", sa.String(36), sa.ForeignKey("memories.id"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("model_id", sa.String(64), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("embedding", Vector().with_variant(sa.JSON(), "sqlite"), nullable=False),
        sa.UniqueConstraint("memory_id", "model_id"),
    )
    op.create_index("ix_memory_embeddings_memory_id", "memory_embeddings", ["memory_id"])
    op.create_index("ix_memory_embeddings_model_id", "memory_embeddings", ["model_id"])
    op.create_table(
        "deletion_receipts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("applied_at", sa.Float(), nullable=False),
    )
    op.create_index("ix_deletion_receipts_user_id", "deletion_receipts", ["user_id"])


def downgrade():
    op.drop_table("deletion_receipts")
    op.drop_table("memory_embeddings")
