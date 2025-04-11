from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db.models import Movement


class EventType(str, Enum):
    """Перечисление типов событий для API и внутренних нужд."""

    ARRIVAL = "arrival"
    DEPARTURE = "departure"


class WarehouseStockResponse(BaseModel):
    """Схема ответа для запроса остатков товара на складе."""

    warehouse_id: str = Field(..., description="ID склада")
    product_id: str = Field(..., description="ID товара")
    quantity: int = Field(..., description="Текущее количество товара на складе")

    model_config = ConfigDict(from_attributes=True)


class MovementEventData(BaseModel):
    """Схема для валидации поля 'data' внутри сообщения Kafka."""

    movement_id: str
    warehouse_id: str
    timestamp: str
    event: str
    product_id: str
    quantity: int

    @field_validator("timestamp")
    def validate_timestamp_format(cls, v):
        """Валидирует формат ISO 8601 для timestamp."""
        try:
            datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError(
                "Invalid timestamp format. Expected ISO 8601 format (e.g., '2025-02-18T14:34:56Z')"
            )
        return v

    @field_validator("event")
    def validate_event_type(cls, v):
        """Валидирует значение поля event."""
        allowed_events = {e.value for e in EventType}
        if v.lower() not in allowed_events:
            raise ValueError(
                f"Invalid event type. Must be one of: {', '.join(allowed_events)}"
            )
        return v.lower()


class KafkaMessage(BaseModel):
    """Схема для валидации всего сообщения из Kafka."""

    id: str
    source: str
    specversion: str
    type: str
    datacontenttype: str
    dataschema: str
    time: int
    subject: str
    destination: str
    data: MovementEventData

    @field_validator("time")
    def validate_time_positive(cls, v):
        """Проверяет, что timestamp положительный."""
        if v < 0:
            raise ValueError("Timestamp 'time' must be a positive integer.")
        return v


class MovementDetailResponse(BaseModel):
    """Схема ответа для запроса детальной информации о перемещении."""

    id: str = Field(..., description="ID перемещения")
    product_id: str = Field(..., description="ID товара")
    source_warehouse_id: Optional[str] = Field(
        None, description="ID склада-отправителя"
    )
    destination_warehouse_id: Optional[str] = Field(
        None, description="ID склада-получателя"
    )
    departure_timestamp: Optional[datetime] = Field(
        None, description="Время отправки (UTC)"
    )
    arrival_timestamp: Optional[datetime] = Field(
        None, description="Время прибытия (UTC)"
    )
    departure_quantity: Optional[int] = Field(
        None, description="Количество при отправке"
    )
    arrival_quantity: Optional[int] = Field(None, description="Количество при прибытии")
    transfer_time: Optional[float] = Field(
        None, description="Время перемещения в секундах (если доступно)"
    )
    quantity_difference: Optional[int] = Field(
        None, description="Разница в количестве (прибытие - отправка, если доступно)"
    )
    is_complete: bool = Field(
        ...,
        description="Флаг, указывающий, получены ли оба события (отправка и прибытие)",
    )

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_db_model(cls, db_model: "Movement") -> "MovementDetailResponse":
        """
        Фабричный метод для создания объекта ответа из ORM модели Movement.
        Вычисляет 'is_complete'.
        """
        return cls(
            id=db_model.id,
            product_id=db_model.product_id,
            source_warehouse_id=db_model.source_warehouse_id,
            destination_warehouse_id=db_model.destination_warehouse_id,
            departure_timestamp=db_model.departure_timestamp,
            arrival_timestamp=db_model.arrival_timestamp,
            departure_quantity=db_model.departure_quantity,
            arrival_quantity=db_model.arrival_quantity,
            transfer_time=db_model.transfer_time,
            quantity_difference=db_model.quantity_difference,
            # Перемещение считается завершенным, если есть оба временных штампа
            is_complete=db_model.departure_timestamp is not None
            and db_model.arrival_timestamp is not None,
        )


class ErrorResponse(BaseModel):
    """Стандартная схема ответа для ошибок."""

    detail: str = Field(..., description="Описание ошибки")
