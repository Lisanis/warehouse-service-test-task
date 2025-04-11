import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from aiokafka import AIOKafkaConsumer, TopicPartition
from aiokafka.errors import KafkaError
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.api.schemas import KafkaMessage
from app.cache.manager import CacheManager, get_cache_manager
from app.config import KAFKA_BOOTSTRAP_SERVERS, KAFKA_GROUP_ID, KAFKA_TOPIC
from app.db.database import AsyncSessionLocal
from app.db.models import EventType
from app.services.warehouse import WarehouseService

logger = logging.getLogger(__name__)


CONSUMER_CONFIG = {
    "bootstrap_servers": KAFKA_BOOTSTRAP_SERVERS,
    "group_id": KAFKA_GROUP_ID,
    "auto_offset_reset": "earliest",
    "enable_auto_commit": False,
    "max_poll_records": 50,
    "max_poll_interval_ms": 300000,
    "session_timeout_ms": 30000,
    "heartbeat_interval_ms": 10000,
    "fetch_max_wait_ms": 500,
}


class KafkaConsumerService:
    """
    Сервис для асинхронного потребления сообщений из Kafka,
    их валидации, обработки с помощью WarehouseService и ручного коммита offset'ов.
    """

    def __init__(self):
        self.consumer: Optional[AIOKafkaConsumer] = None
        self._running = False
        self._cache_manager: Optional[CacheManager] = None

    async def start(self):
        """
        Инициализирует и запускает Kafka consumer.
        Выполняет цикл потребления сообщений до вызова stop().
        """
        # Получаем CacheManager один раз при старте
        self._cache_manager = get_cache_manager()
        if not self._cache_manager:
            logger.error("Failed to get Cache Manager. Kafka Consumer cannot start.")
            return

        while not self._running:
            try:
                logger.info(
                    f"Initializing Kafka consumer with config: {CONSUMER_CONFIG}"
                )
                self.consumer = AIOKafkaConsumer(KAFKA_TOPIC, **CONSUMER_CONFIG)
                await self.consumer.start()
                self._running = True
                logger.info(
                    f"Kafka consumer started successfully. Listening to topic: '{KAFKA_TOPIC}'"
                )
                await self._consume_messages()
            except KafkaError as e:
                logger.error(
                    f"Failed to start Kafka consumer: {e}. Retrying in 10 seconds..."
                )
                if self.consumer:
                    try:
                        await self.consumer.stop()
                    except Exception as stop_err:
                        logger.warning(
                            f"Error stopping consumer during retry: {stop_err}"
                        )
                self.consumer = None
                self._running = False
                await asyncio.sleep(10)
            except Exception as e:
                logger.error(
                    f"Unexpected error during Kafka consumer start: {e}", exc_info=True
                )

                await self.stop()
                break

    async def stop(self):
        """Останавливает Kafka consumer."""
        self._running = False
        if self.consumer:
            logger.info("Stopping Kafka consumer...")
            try:
                await self.consumer.stop()
                logger.info("Kafka consumer stopped.")
            except Exception as e:
                logger.error(f"Error stopping Kafka consumer: {e}", exc_info=True)
            finally:
                self.consumer = None

    async def _consume_messages(self):
        """Основной цикл потребления и обработки сообщений."""
        if not self.consumer:
            logger.error("Consumer is not initialized in _consume_messages.")
            return

        while self._running:
            try:
                # Получаем пачку сообщений
                result = await self.consumer.getmany(
                    timeout_ms=1000, max_records=CONSUMER_CONFIG["max_poll_records"]
                )

                # Обрабатываем сообщения по партициям
                for tp, messages in result.items():
                    logger.debug(f"Received {len(messages)} messages from {tp}")
                    last_processed_offset = -1
                    try:
                        for message in messages:
                            log_prefix = f"[Topic: {message.topic}, Partition: {message.partition}, Offset: {message.offset}, Key: {message.key}]"
                            logger.debug(f"{log_prefix} Received raw message.")

                            # Обрабатываем одно сообщение
                            success = await self._process_message_wrapper(
                                message, log_prefix
                            )

                            if success:
                                last_processed_offset = message.offset
                            else:
                                logger.warning(
                                    f"{log_prefix} Processing failed. Offset will not be committed for this partition batch. Consider implementing DLQ."
                                )

                        if last_processed_offset >= 0:
                            offset_to_commit = last_processed_offset + 1
                            logger.debug(
                                f"Committing offset {offset_to_commit} for partition {tp}"
                            )
                            await self.consumer.commit({tp: offset_to_commit})

                    except Exception as batch_error:
                        logger.error(
                            f"Error processing batch for partition {tp}: {batch_error}",
                            exc_info=True,
                        )

            except KafkaError as e:
                logger.error(
                    f"Kafka error during message consumption: {e}. Attempting recovery..."
                )

                await asyncio.sleep(5)
            except Exception as e:
                logger.error(
                    f"Unexpected error in consumption loop: {e}", exc_info=True
                )

                await asyncio.sleep(5)

    async def _process_message_wrapper(self, message, log_prefix) -> bool:
        """Обертка для обработки одного сообщения с обработкой исключений и транзакцией."""
        try:
            # 1. Декодирование и парсинг JSON
            try:
                message_value = message.value.decode("utf-8")
                raw_data = json.loads(message_value)
            except (UnicodeDecodeError, json.JSONDecodeError) as e:
                logger.error(
                    f"{log_prefix} Failed to decode or parse JSON: {e}. Raw value: {message.value[:200]}..."
                )  # Логируем начало сообщения

                return True

            # 2. Валидация структуры сообщения с помощью Pydantic
            try:
                kafka_message = KafkaMessage.model_validate(raw_data)
                logger.debug(
                    f"{log_prefix} Message validated successfully. ID: {kafka_message.id}"
                )
            except ValidationError as e:
                logger.error(
                    f"{log_prefix} Message validation failed: {e}. Data: {raw_data}"
                )

                return True

            # 3. Подготовка данных для сервисного слоя
            processed_data = self._prepare_event_data(kafka_message, log_prefix)
            if not processed_data:
                logger.warning(
                    f"{log_prefix} Failed to prepare data for event service. Skipping message."
                )
                return True

            # 4. Обработка события в рамках транзакции БД
            async with AsyncSessionLocal() as session:
                try:
                    warehouse_service = WarehouseService(session, self._cache_manager)

                    processed = await warehouse_service.process_movement_event(
                        processed_data
                    )

                    if processed:
                        await session.commit()
                        logger.info(
                            f"{log_prefix} Event processed and transaction committed. Message ID: {kafka_message.id}"
                        )
                        return True
                    else:
                        logger.info(
                            f"{log_prefix} Event was already processed. Skipping commit. Message ID: {kafka_message.id}"
                        )
                        return True

                except (ValueError, SQLAlchemyError) as e:
                    logger.error(
                        f"{log_prefix} Error during warehouse service processing or commit: {e}",
                        exc_info=True,
                    )
                    await session.rollback()
                    return False
                except Exception as e:
                    logger.error(
                        f"{log_prefix} Unexpected error during service execution: {e}",
                        exc_info=True,
                    )
                    await session.rollback()
                    return False

        except Exception as e:
            logger.error(
                f"{log_prefix} Critical error processing message: {e}", exc_info=True
            )
            return False

    def _prepare_event_data(
        self, kafka_message: KafkaMessage, log_prefix: str
    ) -> Optional[Dict[str, Any]]:
        """Извлекает и подготавливает данные из валидированного сообщения Kafka для WarehouseService."""
        try:
            event_data = kafka_message.data
            message_id = kafka_message.id
            message_source = kafka_message.source

            message_time = datetime.fromtimestamp(
                kafka_message.time / 1000, tz=timezone.utc
            )
            subject = kafka_message.subject

            event_type = EventType(event_data.event)

            # Преобразуем строку timestamp в datetime
            try:
                timestamp = datetime.fromisoformat(
                    event_data.timestamp.replace("Z", "+00:00")
                )

                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=timezone.utc)
            except ValueError:
                logger.warning(
                    f"{log_prefix} Invalid timestamp format in data: {event_data.timestamp}"
                )
                return None

            # Собираем финальный словарь для сервиса
            processed_data = {
                "message_id": message_id,
                "message_source": message_source,
                "message_time": message_time,
                "movement_id": event_data.movement_id,
                "warehouse_id": event_data.warehouse_id,
                "timestamp": timestamp,
                "event_type": event_type,
                "product_id": event_data.product_id,
                "quantity": event_data.quantity,
            }
            return processed_data

        except Exception as e:
            logger.error(
                f"{log_prefix} Error preparing data from KafkaMessage: {e}",
                exc_info=True,
            )
            return None
