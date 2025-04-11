import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, Optional

import redis.asyncio as redis

from app.config import CACHE_TTL, REDIS_DB, REDIS_HOST, REDIS_PORT

logger = logging.getLogger(__name__)


class CacheManager:
    """Управляет соединением с Redis и операциями кэширования."""

    def __init__(self):
        self.redis_client: Optional[redis.Redis] = None
        self.ttl = CACHE_TTL
        logger.info("CacheManager instance created (connection not yet established).")

    async def connect(self):
        """Устанавливает соединение с Redis."""
        if self.redis_client is None:
            logger.info(
                f"Connecting to Redis at {REDIS_HOST}:{REDIS_PORT} DB {REDIS_DB}..."
            )
            try:
                self.redis_client = redis.Redis(
                    host=REDIS_HOST,
                    port=REDIS_PORT,
                    db=REDIS_DB,
                    decode_responses=True,  # Важно для получения строк, а не байт
                    socket_connect_timeout=5,  # Таймаут подключения
                )
                # Проверяем соединение
                await self.redis_client.ping()
                logger.info("Successfully connected to Redis and pinged.")
            except Exception as e:
                logger.error(f"Failed to connect to Redis: {e}", exc_info=True)
                self.redis_client = None  # Сбрасываем клиент при ошибке
                raise  # Перебрасываем ошибку, чтобы инициализация провалилась

    async def close(self):
        """Закрывает соединение с Redis."""
        if self.redis_client:
            logger.info("Closing Redis connection...")
            try:
                await self.redis_client.close()
                logger.info("Redis connection closed.")
            except Exception as e:
                logger.error(f"Error closing Redis connection: {e}", exc_info=True)
            finally:
                self.redis_client = None

    async def get(self, key: str) -> Optional[Dict[str, Any]]:
        """Получает значение из кэша по ключу."""
        if not self.redis_client:
            logger.warning(
                "Attempted GET from cache, but Redis client is not connected."
            )
            return None
        try:
            data = await self.redis_client.get(key)
            if data:
                # Здесь может быть ошибка десериализации, если данные не JSON
                try:
                    return json.loads(data)
                except json.JSONDecodeError:
                    logger.warning(
                        f"Failed to decode JSON from cache key {key}. Data: {data}"
                    )
                    return None  # Или удалить ключ? self.delete(key)
            return None
        except Exception as e:
            logger.error(f"Error getting key {key} from Redis: {e}", exc_info=True)
            return None  # Не удалось получить из кэша

    async def set(
        self, key: str, value: Dict[str, Any], ttl: Optional[int] = None
    ) -> None:
        """Устанавливает значение в кэше с опциональным TTL."""
        if not self.redis_client:
            logger.warning("Attempted SET to cache, but Redis client is not connected.")
            return
        try:

            def serialize_datetime(obj):
                if isinstance(obj, datetime):
                    return obj.isoformat()
                return obj

            await self.redis_client.set(
                key,
                json.dumps(
                    value, default=serialize_datetime
                ),  # Сериализуем в JSON с обработкой datetime
                ex=ttl if ttl is not None else self.ttl,
            )
        except Exception as e:
            logger.error(f"Error setting key {key} in Redis: {e}", exc_info=True)

    async def delete(self, key: str) -> None:
        """Удаляет ключ из кэша."""
        if not self.redis_client:
            logger.warning(
                "Attempted DELETE from cache, but Redis client is not connected."
            )
            return
        try:
            await self.redis_client.delete(key)
        except Exception as e:
            logger.error(f"Error deleting key {key} from Redis: {e}", exc_info=True)

    # ... (метод clear_pattern, если нужен) ...


# --- Синглтон и Управление ---
_cache_manager_instance: Optional[CacheManager] = None
_init_lock = asyncio.Lock()


async def initialize_cache() -> None:
    """Инициализирует глобальный экземпляр CacheManager и подключается к Redis."""
    global _cache_manager_instance
    async with _init_lock:
        if _cache_manager_instance is None:
            logger.info("Initializing global CacheManager instance...")
            instance = CacheManager()
            try:
                await instance.connect()  # Пытаемся подключиться
                _cache_manager_instance = (
                    instance  # Присваиваем только после успешного connect
                )
                logger.info("Global CacheManager instance initialized successfully.")
            except Exception as e:
                logger.error(
                    f"CacheManager initialization failed during connection: {e}"
                )
                # _cache_manager_instance остается None
                raise  # Перебрасываем ошибку, чтобы main.py знал о провале


async def close_cache_connection() -> None:
    """Закрывает соединение глобального CacheManager."""
    global _cache_manager_instance
    if _cache_manager_instance:
        await _cache_manager_instance.close()
        _cache_manager_instance = None  # Сбрасываем экземпляр
    else:
        logger.info(
            "Cache connection close requested, but instance was not initialized."
        )


def get_cache_manager() -> CacheManager:
    """
    Зависимость FastAPI для получения инициализированного CacheManager.
    Выбрасывает ошибку, если инициализация не удалась при старте приложения.
    """
    if _cache_manager_instance is None:
        # Если мы здесь, значит initialize_cache() не был вызван или провалился
        logger.critical(
            "FATAL: get_cache_manager() called but CacheManager is not initialized!"
        )

    return _cache_manager_instance


# Добавляем импорт json в начало файла
import json
