"""guardar URL de escudos de equipos

Revision ID: a6b7c8d9e0f1
Revises: e5f6a7b8c9d0
"""

from alembic import op
import sqlalchemy as sa


revision = "a6b7c8d9e0f1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("equipos", sa.Column("escudo_url", sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column("equipos", "escudo_url")
