"""selecciones simuladas para seguimiento de cuotas

Revision ID: f1b2c3d4e5f6
Revises: d7a60b4c129e
"""

from alembic import op
import sqlalchemy as sa


revision = "f1b2c3d4e5f6"
down_revision = "d7a60b4c129e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "selecciones_seguimiento",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("partido_id", sa.Integer(), sa.ForeignKey("partidos.id"), nullable=False),
        sa.Column("pronostico_id", sa.Integer(), sa.ForeignKey("pronosticos.id"), nullable=False),
        sa.Column("cuota_id", sa.Integer(), sa.ForeignKey("cuotas.id"), nullable=False),
        sa.Column("lado", sa.String(10), nullable=False),
        sa.Column("probabilidad", sa.Float(), nullable=False),
        sa.Column("cuota_decimal", sa.Float(), nullable=False),
        sa.Column("casa", sa.String(80), nullable=False),
        sa.Column("seleccionada_en", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("pronostico_id", name="uq_seleccion_pronostico"),
        sa.UniqueConstraint("cuota_id", name="uq_seleccion_cuota"),
    )
    op.create_index("ix_selecciones_seguimiento_partido_id", "selecciones_seguimiento", ["partido_id"])
    op.create_index("ix_selecciones_seguimiento_seleccionada_en", "selecciones_seguimiento", ["seleccionada_en"])


def downgrade() -> None:
    op.drop_index("ix_selecciones_seguimiento_seleccionada_en", table_name="selecciones_seguimiento")
    op.drop_index("ix_selecciones_seguimiento_partido_id", table_name="selecciones_seguimiento")
    op.drop_table("selecciones_seguimiento")
