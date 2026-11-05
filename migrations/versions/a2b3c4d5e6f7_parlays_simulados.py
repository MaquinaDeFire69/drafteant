"""parlays simulados y piernas fijadas

Revision ID: a2b3c4d5e6f7
Revises: f1b2c3d4e5f6
"""

from alembic import op
import sqlalchemy as sa


revision = "a2b3c4d5e6f7"
down_revision = "f1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "parlays_simulados",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("origen", sa.String(12), nullable=False),
        sa.Column("casa", sa.String(80), nullable=False),
        sa.Column("probabilidad", sa.Float(), nullable=False),
        sa.Column("cuota_decimal", sa.Float(), nullable=False),
        sa.Column("monto", sa.Float(), nullable=False),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_parlays_simulados_creado_en", "parlays_simulados", ["creado_en"])
    op.create_table(
        "piernas_parlay",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("parlay_id", sa.Integer(), sa.ForeignKey("parlays_simulados.id"), nullable=False),
        sa.Column("partido_id", sa.Integer(), sa.ForeignKey("partidos.id"), nullable=False),
        sa.Column("pronostico_id", sa.Integer(), sa.ForeignKey("pronosticos.id"), nullable=False),
        sa.Column("lado", sa.String(10), nullable=False),
        sa.Column("probabilidad", sa.Float(), nullable=False),
        sa.Column("cuota_decimal", sa.Float(), nullable=False),
        sa.UniqueConstraint("parlay_id", "partido_id", name="uq_pierna_parlay_partido"),
    )
    op.create_index("ix_piernas_parlay_parlay_id", "piernas_parlay", ["parlay_id"])


def downgrade() -> None:
    op.drop_index("ix_piernas_parlay_parlay_id", table_name="piernas_parlay")
    op.drop_table("piernas_parlay")
    op.drop_index("ix_parlays_simulados_creado_en", table_name="parlays_simulados")
    op.drop_table("parlays_simulados")
