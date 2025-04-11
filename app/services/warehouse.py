import logging
from typing import Any, Dict

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.manager import CacheManager
from app.db.crud import (
    MovementEventRepository,
    MovementRepository,
    ProductRepository,
    WarehouseRepository,
    WarehouseStockRepository,
)
from app.db.models import EventType

logger = logging.getLogger(__name__)


class WarehouseService:
    """
    Сервисный слой для обработки бизнес-логики, связанной со складами и перемещениями.
    Инкапсулирует работу с репозиториями и кэшем.
    """

    def __init__(self, session: AsyncSession, cache_manager: CacheManager):
        """
        Инициализирует сервис с сессией БД и менеджером кэша.

        Args:
            session: Асинхронная сессия SQLAlchemy.
            cache_manager: Экземпляр CacheManager.
        """
        self.session = session
        self.product_repo = ProductRepository(session)
        self.warehouse_repo = WarehouseRepository(session)
        self.stock_repo = WarehouseStockRepository(session)
        self.movement_repo = MovementRepository(session)
        self.event_repo = MovementEventRepository(session)
        self.cache_manager = cache_manager

    async def process_movement_event(self, event_data: Dict[str, Any]) -> bool:
        """
        Обрабатывает одно событие перемещения товара (прибытие или отправка).

        Выполняет следующие шаги в рамках одной транзакции:
        1. Проверяет идемпотентность (не обрабатывалось ли событие ранее).
        2. Получает или создает записи Product и Warehouse.
        3. Атомарно обновляет остатки на складе (WarehouseStock), обрабатывая возможные ошибки (например, отрицательный остаток).
        4. Создает или обновляет запись о полном перемещении (Movement).
        5. Логирует обработанное событие (MovementEvent).
        6. Инвалидирует соответствующие записи в кэше.

        Args:
            event_data: Словарь с данными обработанного и валидированного события Kafka.

        Returns:
            True, если событие успешно обработано, False - если событие уже было обработано ранее.

        Raises:
            ValueError: Если обновление стока приводит к недопустимому состоянию (например, отрицательный остаток).
            SQLAlchemyError: При других ошибках базы данных.
        """
        message_id = event_data["message_id"]
        movement_id = event_data["movement_id"]
        warehouse_id = event_data["warehouse_id"]
        product_id = event_data["product_id"]
        event_type = event_data["event_type"]
        quantity = event_data["quantity"]

        try:
            # 1. Проверка идемпотентности
            if await self.event_repo.is_event_processed(message_id):
                logger.warning(
                    f"Event with message ID {message_id} already processed. Skipping."
                )
                return False

            # Начало неявной транзакции (управляется контекстным менеджером сессии в вызывающем коде)

            # 2. Получаем или создаем Product и Warehouse
            product = await self.product_repo.get_or_create(product_id)
            warehouse = await self.warehouse_repo.get_or_create(warehouse_id)

            # 3. Обновляем остатки на складе
            quantity_delta = quantity if event_type == EventType.ARRIVAL else -quantity
            try:
                await self.stock_repo.create_or_update_stock(
                    warehouse_id, product_id, quantity_delta
                )
                logger.info(
                    f"Stock updated for warehouse {warehouse_id}, product {product_id}. Delta: {quantity_delta}"
                )
            except ValueError as e:
                logger.error(f"Failed to update stock for event {message_id}: {e}")
                raise

            # 4. Создаем или обновляем информацию о перемещении (Movement)
            movement = await self.movement_repo.create_or_update(event_data)
            logger.info(f"Movement {movement.id} updated with {event_type} event.")

            # 5. Логируем обработанное событие (MovementEvent)
            await self.event_repo.create(event_data)
            logger.info(f"MovementEvent {message_id} logged successfully.")

            # 6. Инвалидация кэша ПОСЛЕ успешного коммита транзакции
            await self._invalidate_cache(warehouse_id, product_id, movement_id)

            return True

        except SQLAlchemyError as e:
            logger.error(
                f"Database error processing event {message_id}: {e}", exc_info=True
            )
            raise
        except Exception as e:
            logger.error(
                f"Unexpected error processing event {message_id}: {e}", exc_info=True
            )
            raise

    async def _invalidate_cache(
        self, warehouse_id: str, product_id: str, movement_id: str
    ):
        """
        Инвалидирует (удаляет) связанные записи из кэша.
        Вызывается после успешной обработки события и коммита транзакции.
        """
        stock_cache_key = f"stock:{warehouse_id}:{product_id}"
        movement_cache_key = f"movement:{movement_id}"

        deleted_stock = await self.cache_manager.delete(stock_cache_key)
        if deleted_stock:
            logger.debug(f"Cache invalidated for key: {stock_cache_key}")

        deleted_movement = await self.cache_manager.delete(movement_cache_key)
        if deleted_movement:
            logger.debug(f"Cache invalidated for key: {movement_cache_key}")
