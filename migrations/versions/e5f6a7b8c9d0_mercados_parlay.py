"""Cuotas de goles/ambos anotan y mercado de cada pierna.

Revision ID: e5f6a7b8c9d0
Revises: c4d5e6f7a8b9
"""

from alembic import op
import sqlalchemy as sa

revision = "e5f6a7b8c9d0"
down_revision = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("pronosticos", sa.Column("prob_mas_2_5", sa.Float(), nullable=True))
    op.add_column("pronosticos", sa.Column("prob_ambos_anotan", sa.Float(), nullable=True))
    op.create_table(
        "cuotas_mercado",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("partido_id", sa.Integer(), sa.ForeignKey("partidos.id"), nullable=False),
        sa.Column("evento_api_id", sa.String(80), nullable=False),
        sa.Column("casa", sa.String(80), nullable=False),
        sa.Column("mercado", sa.String(20), nullable=False),
        sa.Column("opcion", sa.String(10), nullable=False),
        sa.Column("linea", sa.Float(), nullable=False, server_default="0"),
        sa.Column("cuota_decimal", sa.Float(), nullable=False),
        sa.Column("actualizada_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("capturada_en", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("evento_api_id", "casa", "mercado", "opcion", "linea", "actualizada_en",
                            name="uq_cuota_mercado_actualizacion"),
    )
    op.create_index("ix_cuotas_mercado_partido_id", "cuotas_mercado", ["partido_id"])
    op.create_index("ix_cuotas_mercado_capturada_en", "cuotas_mercado", ["capturada_en"])
    op.add_column("piernas_parlay", sa.Column("mercado", sa.String(20), nullable=False, server_default="h2h"))


def downgrade() -> None:
    op.drop_column("pronosticos", "prob_ambos_anotan")
    op.drop_column("pronosticos", "prob_mas_2_5")
    op.drop_column("piernas_parlay", "mercado")
    op.drop_index("ix_cuotas_mercado_capturada_en", table_name="cuotas_mercado")
    op.drop_index("ix_cuotas_mercado_partido_id", table_name="cuotas_mercado")
    op.drop_table("cuotas_mercado")
