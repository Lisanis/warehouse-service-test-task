from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.database import get_db
from app.db.models import (
    EventType,
    Movement,
    MovementEvent,
    Product,
    Warehouse,
    WarehouseStock,
)


class ProductRepository:
    """Репозиторий для операций с товарами (Product)."""

    def __init__(self, session: AsyncSession = Depends(get_db)):
        self.session = session

    async def get_by_id(self, product_id: str) -> Optional[Product]:
        """Получает товар по его ID."""
        result = await self.session.execute(
            select(Product).where(Product.id == product_id)
        )
        return result.scalars().first()

    async def get_or_create(self, product_id: str) -> Product:
        """Получает товар по ID или создает новый, если он не существует."""
        product = await self.get_by_id(product_id)
        if not product:
            product = Product(id=product_id)
            self.session.add(product)
            await self.session.flush()
            await self.session.refresh(product)
        return product


class WarehouseRepository:
    """Репозиторий для операций со складами (Warehouse)."""

    def __init__(self, session: AsyncSession = Depends(get_db)):
        self.session = session

    async def get_by_id(self, warehouse_id: str) -> Optional[Warehouse]:
        """Получает склад по его ID."""
        result = await self.session.execute(
            select(Warehouse).where(Warehouse.id == warehouse_id)
        )
        return result.scalars().first()

    async def get_or_create(self, warehouse_id: str) -> Warehouse:
        """Получает склад по ID или создает новый, если он не существует."""
        warehouse = await self.get_by_id(warehouse_id)
        if not warehouse:
            warehouse = Warehouse(id=warehouse_id)
            self.session.add(warehouse)
            await self.session.flush()
            await self.session.refresh(warehouse)
        return warehouse


class WarehouseStockRepository:
    """Репозиторий для операций с остатками товаров на складах (WarehouseStock)."""

    def __init__(self, session: AsyncSession = Depends(get_db)):
        self.session = session

    async def get_stock(
        self, warehouse_id: str, product_id: str, for_update: bool = False
    ) -> Optional[WarehouseStock]:
        """
        Получает остаток товара на складе.

        Args:
            warehouse_id: ID склада.
            product_id: ID товара.
            for_update: Если True, блокирует строку с использованием SELECT ... FOR UPDATE
                        для предотвращения race condition при обновлении.

        Returns:
            Объект WarehouseStock или None, если остаток не найден.
        """
        stmt = select(WarehouseStock).where(
            WarehouseStock.warehouse_id == warehouse_id,
            WarehouseStock.product_id == product_id,
        )
        if for_update:
            # Блокируем строку на время транзакции
            stmt = stmt.with_for_update()

        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def create_or_update_stock(
        self, warehouse_id: str, product_id: str, quantity_delta: int
    ) -> WarehouseStock:
        """
        Атомарно обновляет или создает остаток товара на складе.

        Использует SELECT FOR UPDATE для блокировки строки и предотвращения race conditions.
        Гарантирует, что количество товара не станет отрицательным.

        Args:
            warehouse_id: ID склада.
            product_id: ID товара.
            quantity_delta: Изменение количества (положительное для прихода, отрицательное для расхода).

        Returns:
            Обновленный или созданный объект WarehouseStock.

        Raises:
            ValueError: Если обновление приведет к отрицательному остатку.
        """
        # Пытаемся получить и заблокировать существующую строку остатка
        stock = await self.get_stock(warehouse_id, product_id, for_update=True)

        if stock:
            # Обновляем существующий запас
            new_quantity = stock.quantity + quantity_delta

            # КРИТИЧЕСКАЯ ПРОВЕРКА: не допускаем отрицательных остатков
            if new_quantity < 0:
                raise ValueError(
                    f"Operation failed: Cannot reduce stock below zero for warehouse {warehouse_id} "
                    f"and product {product_id}. Current stock: {stock.quantity}, attempted change: {quantity_delta}"
                )

            stock.quantity = new_quantity
            await self.session.flush()
            await self.session.refresh(stock)
            return stock
        else:
            # Создаем новый запас, только если изменение положительное (инициализация)
            # или если изменение отрицательное, но равно нулю (крайне редкий случай)
            if quantity_delta < 0:
                # Нельзя создать запись с отрицательным начальным количеством
                # Это может произойти, если сообщение об отбытии пришло раньше сообщения о прибытии
                # или если товара никогда не было на складе.
                raise ValueError(
                    f"Operation failed: Cannot initialize stock with negative quantity for warehouse {warehouse_id} "
                    f"and product {product_id}. Attempted change: {quantity_delta}"
                )

            stock = WarehouseStock(
                warehouse_id=warehouse_id,
                product_id=product_id,
                quantity=quantity_delta,  # Начальное количество
            )
            self.session.add(stock)
            await self.session.flush()
            await self.session.refresh(stock)
            return stock


class MovementRepository:
    """Репозиторий для операций с перемещениями (Movement)."""

    def __init__(self, session: AsyncSession = Depends(get_db)):
        self.session = session

    async def get_by_id(self, movement_id: str) -> Optional[Movement]:
        """Получает перемещение по его ID."""
        # Используем selectinload для возможной предзагрузки связанных объектов, если потребуется
        stmt = (
            select(Movement)
            .where(Movement.id == movement_id)
            .options(
                selectinload(Movement.source_warehouse),
                selectinload(Movement.destination_warehouse),
                selectinload(Movement.product),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def create_or_update(self, event_data: Dict[str, Any]) -> Movement:
        """
        Создает или обновляет запись о перемещении на основе данных события.

        Находит существующее перемещение по movement_id или создает новое.
        Обновляет соответствующие поля (отправка/прибытие) на основе типа события.
        Вычисляет transfer_time и quantity_difference, если доступны обе части перемещения.

        Args:
            event_data: Словарь с данными обработанного события Kafka.

        Returns:
            Созданный или обновленный объект Movement.
        """
        movement_id = event_data["movement_id"]
        product_id = event_data["product_id"]
        event_type = event_data["event_type"]
        warehouse_id = event_data["warehouse_id"]
        timestamp = event_data["timestamp"]
        quantity = event_data["quantity"]

        # Пытаемся получить существующее перемещение
        movement = await self.get_by_id(movement_id)

        if not movement:
            # Создаем новое перемещение, если не найдено
            movement = Movement(
                id=movement_id,
                product_id=product_id
                # Остальные поля будут заполнены ниже
            )
            self.session.add(movement)
            # Не делаем flush здесь, сделаем после обновления полей

        # Обновляем данные в зависимости от типа события
        if event_type == EventType.DEPARTURE:
            movement.source_warehouse_id = warehouse_id
            movement.departure_timestamp = timestamp
            movement.departure_quantity = quantity
        elif event_type == EventType.ARRIVAL:
            movement.destination_warehouse_id = warehouse_id
            movement.arrival_timestamp = timestamp
            movement.arrival_quantity = quantity
        else:
            # На всякий случай, хотя тип должен быть проверен раньше
            raise ValueError(f"Unknown event type: {event_type}")

        # Рассчитываем разницу во времени и количестве, если есть оба события
        if movement.departure_timestamp and movement.arrival_timestamp:
            # Вычисляем время передачи в секундах
            # Убедимся, что arrival > departure, иначе результат может быть странным
            if movement.arrival_timestamp >= movement.departure_timestamp:
                transfer_time = (
                    movement.arrival_timestamp - movement.departure_timestamp
                ).total_seconds()
                movement.transfer_time = transfer_time
            else:
                # Логируем или обрабатываем ситуацию, когда прибытие раньше отправки
                movement.transfer_time = None

            # Вычисляем разницу в количестве (если оба количества известны)
            if (
                movement.departure_quantity is not None
                and movement.arrival_quantity is not None
            ):
                movement.quantity_difference = (
                    movement.arrival_quantity - movement.departure_quantity
                )
            else:
                movement.quantity_difference = None

        await self.session.flush()
        await self.session.refresh(movement)
        return movement


class MovementEventRepository:
    """Репозиторий для операций с событиями перемещений (MovementEvent)."""

    def __init__(self, session: AsyncSession = Depends(get_db)):
        self.session = session

    async def create(self, event_data: Dict[str, Any]) -> MovementEvent:
        """
        Сохраняет запись об обработанном событии Kafka в БД.

        Args:
            event_data: Словарь с данными обработанного события Kafka.

        Returns:
            Созданный объект MovementEvent.
        """
        event = MovementEvent(
            id=event_data["message_id"],
            movement_id=event_data["movement_id"],
            warehouse_id=event_data["warehouse_id"],
            event_type=event_data["event_type"],
            timestamp=event_data["timestamp"],
            product_id=event_data["product_id"],
            quantity=event_data["quantity"],
            message_id=event_data["message_id"],
            message_source=event_data["message_source"],
            message_time=event_data["message_time"],
        )
        self.session.add(event)
        await self.session.flush()
        await self.session.refresh(event)
        return event

    async def get_by_movement_id(self, movement_id: str) -> List[MovementEvent]:
        """Получает все события, связанные с конкретным перемещением."""
        result = await self.session.execute(
            select(MovementEvent).where(MovementEvent.movement_id == movement_id)
        )
        return result.scalars().all()

    async def is_event_processed(self, message_id: str) -> bool:
        """
        Проверяет, было ли событие с данным ID сообщения Kafka уже обработано.
        Ключевая функция для обеспечения идемпотентности обработчика.

        Args:
            message_id: ID сообщения Kafka.

        Returns:
            True, если событие уже обработано (запись существует), иначе False.
        """
        # Быстрый способ проверить существование по PK
        result = await self.session.execute(
            select(MovementEvent.id).where(MovementEvent.id == message_id)
        )
        return result.scalar_one_or_none() is not None
