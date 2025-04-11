import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    select,
)
from sqlalchemy.orm import relationship

from app.db.database import Base


class EventType(str, enum.Enum):
    """Перечисление для типов событий перемещения."""

    ARRIVAL = "arrival"
    DEPARTURE = "departure"


class Product(Base):
    """Модель данных для товара."""

    __tablename__ = "products"

    id = Column(
        String, primary_key=True, comment="Уникальный идентификатор товара (UUID)"
    )
    # Связь с остатками на складах (один товар может быть на многих складах)
    stocks = relationship("WarehouseStock", back_populates="product", lazy="selectin")
    # Связь с перемещениями (один товар может участвовать во многих перемещениях)
    movements = relationship("Movement", back_populates="product", lazy="selectin")

    def __repr__(self):
        return f"<Product(id={self.id})>"


class Warehouse(Base):
    """Модель данных для склада."""

    __tablename__ = "warehouses"

    id = Column(
        String, primary_key=True, comment="Уникальный идентификатор склада (UUID)"
    )
    # Связь с остатками товаров на этом складе
    stocks = relationship("WarehouseStock", back_populates="warehouse", lazy="selectin")
    # Связь с перемещениями, где этот склад является источником
    movements_as_source = relationship(
        "Movement",
        foreign_keys="Movement.source_warehouse_id",
        back_populates="source_warehouse",
        lazy="selectin",
    )
    # Связь с перемещениями, где этот склад является получателем
    movements_as_destination = relationship(
        "Movement",
        foreign_keys="Movement.destination_warehouse_id",
        back_populates="destination_warehouse",
        lazy="selectin",
    )

    def __repr__(self):
        return f"<Warehouse(id={self.id})>"


class WarehouseStock(Base):
    """
    Модель данных для хранения остатков конкретного товара на конкретном складе.
    """

    __tablename__ = "warehouse_stocks"

    # Составной первичный ключ
    warehouse_id = Column(
        String, ForeignKey("warehouses.id"), primary_key=True, comment="ID склада"
    )
    product_id = Column(
        String, ForeignKey("products.id"), primary_key=True, comment="ID товара"
    )

    quantity = Column(
        Integer,
        default=0,
        nullable=False,
        comment="Текущее количество товара на складе",
    )

    # Связи для удобного доступа к объектам Warehouse и Product
    warehouse = relationship("Warehouse", back_populates="stocks", lazy="selectin")
    product = relationship("Product", back_populates="stocks", lazy="selectin")

    def __repr__(self):
        return f"<WarehouseStock(warehouse={self.warehouse_id}, product={self.product_id}, quantity={self.quantity})>"


class Movement(Base):
    """
    Модель данных для отслеживания полного цикла перемещения товара
    (от отправки до прибытия).
    """

    __tablename__ = "movements"

    id = Column(
        String, primary_key=True, comment="Уникальный идентификатор перемещения (UUID)"
    )
    product_id = Column(
        String,
        ForeignKey("products.id"),
        nullable=False,
        comment="ID перемещаемого товара",
    )

    # Информация об отправке (заполняется событием DEPARTURE)
    source_warehouse_id = Column(
        String,
        ForeignKey("warehouses.id"),
        nullable=True,
        comment="ID склада-отправителя",
    )
    departure_timestamp = Column(
        DateTime(timezone=True), nullable=True, comment="Время отправки"
    )
    departure_quantity = Column(
        Integer, nullable=True, comment="Количество при отправке"
    )

    # Информация о прибытии (заполняется событием ARRIVAL)
    destination_warehouse_id = Column(
        String,
        ForeignKey("warehouses.id"),
        nullable=True,
        comment="ID склада-получателя",
    )
    arrival_timestamp = Column(
        DateTime(timezone=True), nullable=True, comment="Время прибытия"
    )
    arrival_quantity = Column(Integer, nullable=True, comment="Количество при прибытии")

    # Вычисляемые поля (заполняются после получения обоих событий)
    transfer_time = Column(Float, nullable=True, comment="Время перемещения в секундах")
    quantity_difference = Column(
        Integer, nullable=True, comment="Разница в количестве (прибытие - отправка)"
    )

    # Технические поля
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Связи
    product = relationship("Product", back_populates="movements", lazy="selectin")
    source_warehouse = relationship(
        "Warehouse",
        foreign_keys=[source_warehouse_id],
        back_populates="movements_as_source",
        lazy="selectin",
    )
    destination_warehouse = relationship(
        "Warehouse",
        foreign_keys=[destination_warehouse_id],
        back_populates="movements_as_destination",
        lazy="selectin",
    )

    def __repr__(self):
        return f"<Movement(id={self.id}, product={self.product_id})>"


class MovementEvent(Base):
    """
    Модель данных для логирования каждого отдельного события (прибытия или отправки),
    полученного из Kafka. Используется для идемпотентности и отладки.
    """

    __tablename__ = "movement_events"

    # Используем ID сообщения Kafka как первичный ключ для идемпотентности
    id = Column(String, primary_key=True, comment="ID сообщения Kafka")
    movement_id = Column(
        String,
        ForeignKey("movements.id"),
        nullable=False,
        comment="ID связанного перемещения",
    )
    warehouse_id = Column(
        String,
        ForeignKey("warehouses.id"),
        nullable=False,
        comment="ID склада, где произошло событие",
    )
    event_type = Column(
        Enum(EventType), nullable=False, comment="Тип события (arrival/departure)"
    )
    timestamp = Column(
        DateTime(timezone=True),
        nullable=False,
        comment="Время события из данных сообщения",
    )
    product_id = Column(
        String, ForeignKey("products.id"), nullable=False, comment="ID товара"
    )
    quantity = Column(Integer, nullable=False, comment="Количество товара в событии")

    # Время обработки события сервисом
    processed_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Дополнительные метаданные из сообщения Kafka для отладки
    message_id = Column(
        String, comment="Полный ID сообщения Kafka (дублирует первичный ключ)"
    )
    message_source = Column(String, comment="Источник сообщения Kafka (поле source)")
    message_time = Column(
        DateTime(timezone=True), comment="Время сообщения Kafka (поле time)"
    )

    def __repr__(self):
        return f"<MovementEvent(id={self.id}, movement={self.movement_id}, type={self.event_type})>"
