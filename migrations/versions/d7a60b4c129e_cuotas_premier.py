"""capturas de cuotas 1X2 para partidos

Revision ID: d7a60b4c129e
Revises: c82f4d9a1e32
"""

from alembic import op
import sqlalchemy as sa


revision = "d7a60b4c129e"
down_revision = "c82f4d9a1e32"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cuotas",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("partido_id", sa.Integer(), sa.ForeignKey("partidos.id"), nullable=False),
        sa.Column("pronostico_id", sa.Integer(), sa.ForeignKey("pronosticos.id"), nullable=True),
        sa.Column("evento_api_id", sa.String(80), nullable=False),
        sa.Column("casa", sa.String(80), nullable=False),
        sa.Column("cuota_local", sa.Float(), nullable=False),
        sa.Column("cuota_empate", sa.Float(), nullable=False),
        sa.Column("cuota_visitante", sa.Float(), nullable=False),
        sa.Column("actualizada_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("capturada_en", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("evento_api_id", "casa", "actualizada_en", name="uq_cuota_evento_casa_actualizacion"),
    )
    op.create_index("ix_cuotas_partido_id", "cuotas", ["partido_id"])
    op.create_index("ix_cuotas_capturada_en", "cuotas", ["capturada_en"])


def downgrade() -> None:
    op.drop_index("ix_cuotas_capturada_en", table_name="cuotas")
    op.drop_index("ix_cuotas_partido_id", table_name="cuotas")
    op.drop_table("cuotas")
