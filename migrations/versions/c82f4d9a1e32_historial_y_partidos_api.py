"""historial de pronosticos y seguimiento de partidos API

Revision ID: c82f4d9a1e32
Revises: 89c97d1360b8
Create Date: 2026-11-04
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c82f4d9a1e32"
down_revision: Union[str, Sequence[str], None] = "89c97d1360b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("partidos", sa.Column("api_partido_id", sa.Integer(), nullable=True))
    op.add_column("partidos", sa.Column("inicio_utc", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "partidos",
        sa.Column("estado", sa.String(length=20), server_default="SCHEDULED", nullable=False),
    )
    op.execute("UPDATE partidos SET estado = 'FINISHED' WHERE goles_local IS NOT NULL")
    op.create_unique_constraint("uq_partido_api", "partidos", ["api_partido_id"])
    op.create_index("ix_partidos_inicio_utc", "partidos", ["inicio_utc"], unique=False)
    op.create_index("ix_partidos_estado", "partidos", ["estado"], unique=False)

    op.add_column("pronosticos", sa.Column("publicado_en", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_pronosticos_publicado_en", "pronosticos", ["publicado_en"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_pronosticos_publicado_en", table_name="pronosticos")
    op.drop_column("pronosticos", "publicado_en")
    op.drop_index("ix_partidos_estado", table_name="partidos")
    op.drop_index("ix_partidos_inicio_utc", table_name="partidos")
    op.drop_constraint("uq_partido_api", "partidos", type_="unique")
    op.drop_column("partidos", "estado")
    op.drop_column("partidos", "inicio_utc")
    op.drop_column("partidos", "api_partido_id")
