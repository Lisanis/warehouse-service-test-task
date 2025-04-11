"""Testing table

Revision ID: 23d326945a1e
Revises:
Create Date: 2025-04-11 14:40:11.425898

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "23d326945a1e"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "products",
        sa.Column(
            "id",
            sa.String(),
            nullable=False,
            comment="Уникальный идентификатор товара (UUID)",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "warehouses",
        sa.Column(
            "id",
            sa.String(),
            nullable=False,
            comment="Уникальный идентификатор склада (UUID)",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "movements",
        sa.Column(
            "id",
            sa.String(),
            nullable=False,
            comment="Уникальный идентификатор перемещения (UUID)",
        ),
        sa.Column(
            "product_id", sa.String(), nullable=False, comment="ID перемещаемого товара"
        ),
        sa.Column(
            "source_warehouse_id",
            sa.String(),
            nullable=True,
            comment="ID склада-отправителя",
        ),
        sa.Column(
            "departure_timestamp",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Время отправки",
        ),
        sa.Column(
            "departure_quantity",
            sa.Integer(),
            nullable=True,
            comment="Количество при отправке",
        ),
        sa.Column(
            "destination_warehouse_id",
            sa.String(),
            nullable=True,
            comment="ID склада-получателя",
        ),
        sa.Column(
            "arrival_timestamp",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Время прибытия",
        ),
        sa.Column(
            "arrival_quantity",
            sa.Integer(),
            nullable=True,
            comment="Количество при прибытии",
        ),
        sa.Column(
            "transfer_time",
            sa.Float(),
            nullable=True,
            comment="Время перемещения в секундах",
        ),
        sa.Column(
            "quantity_difference",
            sa.Integer(),
            nullable=True,
            comment="Разница в количестве (прибытие - отправка)",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["destination_warehouse_id"],
            ["warehouses.id"],
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
        ),
        sa.ForeignKeyConstraint(
            ["source_warehouse_id"],
            ["warehouses.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "warehouse_stocks",
        sa.Column("warehouse_id", sa.String(), nullable=False, comment="ID склада"),
        sa.Column("product_id", sa.String(), nullable=False, comment="ID товара"),
        sa.Column(
            "quantity",
            sa.Integer(),
            nullable=False,
            comment="Текущее количество товара на складе",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
        ),
        sa.ForeignKeyConstraint(
            ["warehouse_id"],
            ["warehouses.id"],
        ),
        sa.PrimaryKeyConstraint("warehouse_id", "product_id"),
    )
    op.create_table(
        "movement_events",
        sa.Column("id", sa.String(), nullable=False, comment="ID сообщения Kafka"),
        sa.Column(
            "movement_id",
            sa.String(),
            nullable=False,
            comment="ID связанного перемещения",
        ),
        sa.Column(
            "warehouse_id",
            sa.String(),
            nullable=False,
            comment="ID склада, где произошло событие",
        ),
        sa.Column(
            "event_type",
            sa.Enum("ARRIVAL", "DEPARTURE", name="eventtype"),
            nullable=False,
            comment="Тип события (arrival/departure)",
        ),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="Время события из данных сообщения",
        ),
        sa.Column("product_id", sa.String(), nullable=False, comment="ID товара"),
        sa.Column(
            "quantity",
            sa.Integer(),
            nullable=False,
            comment="Количество товара в событии",
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "message_id",
            sa.String(),
            nullable=True,
            comment="Полный ID сообщения Kafka (дублирует первичный ключ)",
        ),
        sa.Column(
            "message_source",
            sa.String(),
            nullable=True,
            comment="Источник сообщения Kafka (поле source)",
        ),
        sa.Column(
            "message_time",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Время сообщения Kafka (поле time)",
        ),
        sa.ForeignKeyConstraint(
            ["movement_id"],
            ["movements.id"],
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
        ),
        sa.ForeignKeyConstraint(
            ["warehouse_id"],
            ["warehouses.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    """Downgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table("movement_events")
    op.drop_table("warehouse_stocks")
    op.drop_table("movements")
    op.drop_table("warehouses")
    op.drop_table("products")
    # ### end Alembic commands ###
