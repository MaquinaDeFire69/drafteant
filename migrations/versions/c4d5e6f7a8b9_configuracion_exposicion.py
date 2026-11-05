"""configuracion de limites de exposicion

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
"""

from alembic import op
import sqlalchemy as sa


revision = "c4d5e6f7a8b9"
down_revision = "b3c4d5e6f7a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "configuracion_exposicion",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("banca_inicial", sa.Float(), nullable=False, server_default="1000"),
        sa.Column("limite_partido", sa.Float(), nullable=False, server_default="0.10"),
        sa.Column("limite_equipo", sa.Float(), nullable=False, server_default="0.20"),
        sa.Column("bloquear_exceso", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("actualizado_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("configuracion_exposicion")
