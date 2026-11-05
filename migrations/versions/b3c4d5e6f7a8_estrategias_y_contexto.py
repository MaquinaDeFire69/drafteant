"""estrategias y contexto de registros simulados

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
"""

from alembic import op
import sqlalchemy as sa

revision = "b3c4d5e6f7a8"
down_revision = "a2b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("estrategias_simulacion",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("nombre", sa.String(80), nullable=False, unique=True),
        sa.Column("liga", sa.String(10)), sa.Column("casa", sa.String(80)),
        sa.Column("min_probabilidad", sa.Float(), nullable=False, server_default="0"),
        sa.Column("min_valor", sa.Float(), nullable=False, server_default="-1"),
        sa.Column("cuota_min", sa.Float()), sa.Column("cuota_max", sa.Float()),
        sa.Column("monto", sa.Float(), nullable=False, server_default="100"),
        sa.Column("creado_en", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.add_column("selecciones_seguimiento", sa.Column("version_modelo", sa.String(30)))
    op.add_column("selecciones_seguimiento", sa.Column("publicado_en", sa.DateTime(timezone=True)))
    op.add_column("selecciones_seguimiento", sa.Column("monto", sa.Float(), nullable=False, server_default="100"))
    op.add_column("selecciones_seguimiento", sa.Column("estado_registro", sa.String(12), nullable=False, server_default="simulada"))
    op.create_index("ix_selecciones_seguimiento_estado_registro", "selecciones_seguimiento", ["estado_registro"])
    op.execute("UPDATE selecciones_seguimiento s SET version_modelo=p.version_modelo, publicado_en=p.publicado_en FROM pronosticos p WHERE p.id=s.pronostico_id")
    op.add_column("parlays_simulados", sa.Column("estado_registro", sa.String(12), nullable=False, server_default="simulada"))
    op.create_index("ix_parlays_simulados_estado_registro", "parlays_simulados", ["estado_registro"])
    op.add_column("piernas_parlay", sa.Column("version_modelo", sa.String(30)))
    op.add_column("piernas_parlay", sa.Column("publicado_en", sa.DateTime(timezone=True)))
    op.execute("UPDATE piernas_parlay l SET version_modelo=p.version_modelo, publicado_en=p.publicado_en FROM pronosticos p WHERE p.id=l.pronostico_id")


def downgrade() -> None:
    op.drop_column("piernas_parlay", "publicado_en"); op.drop_column("piernas_parlay", "version_modelo")
    op.drop_index("ix_parlays_simulados_estado_registro", table_name="parlays_simulados"); op.drop_column("parlays_simulados", "estado_registro")
    op.drop_index("ix_selecciones_seguimiento_estado_registro", table_name="selecciones_seguimiento")
    op.drop_column("selecciones_seguimiento", "estado_registro"); op.drop_column("selecciones_seguimiento", "monto")
    op.drop_column("selecciones_seguimiento", "publicado_en"); op.drop_column("selecciones_seguimiento", "version_modelo")
    op.drop_table("estrategias_simulacion")
