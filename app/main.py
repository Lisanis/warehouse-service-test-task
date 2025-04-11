import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Histogram, make_asgi_app

from app.api.routes import router as api_router
from app.cache.manager import close_cache_connection, initialize_cache
from app.config import API_PREFIX, APP_NAME, APP_VERSION, DEBUG, KAFKA_TOPIC
from app.services.kafka_consumer import KafkaConsumerService

# --- Настройка Логирования ---
logging.basicConfig(
    level=logging.DEBUG if DEBUG else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# --- Инициализация Сервисов ---
kafka_consumer = KafkaConsumerService()

# --- Метрики Prometheus ---
REQUESTS_COUNTER = Counter(
    "http_requests_total", "Total number of HTTP requests", ["method", "path"]
)
REQUEST_LATENCY = Histogram(
    "http_request_latency_seconds",
    "HTTP request latency in seconds",
    ["method", "path"],
)
KAFKA_MESSAGES_COUNTER = Counter(
    "kafka_messages_total", "Total number of Kafka messages processed"
)


# --- Управление Жизненным Циклом Приложения (Lifespan) ---
@asynccontextmanager
async def lifespan(app_instance: FastAPI) -> AsyncGenerator[None, None]:
    """
    Асинхронный контекстный менеджер для управления ресурсами и фоновыми задачами
    во время работы FastAPI приложения.
    """
    logger.info(f"Application startup: {APP_NAME} v{APP_VERSION}")

    # --- Инициализация CacheManager ---
    logger.info("Attempting to initialize Cache Manager...")
    try:
        await initialize_cache()
    except Exception as e:
        logger.error(
            f"FATAL: Cache initialization failed during startup: {e}", exc_info=True
        )

    # --- Запуск Kafka Consumer ---
    logger.info("Starting Kafka consumer...")
    kafka_task = asyncio.create_task(kafka_consumer.start())
    logger.info(f"Kafka consumer scheduled to start listening to topic: {KAFKA_TOPIC}")

    yield

    logger.info("Application shutdown initiated.")

    # 1. Останавливаем Kafka Consumer
    logger.info("Stopping Kafka consumer...")
    await kafka_consumer.stop()
    logger.info("Kafka consumer stop signal sent.")

    # 2. Дожидаемся завершения задачи Kafka (с обработкой отмены)
    if not kafka_task.done():
        logger.debug("Waiting for Kafka consumer task to finish...")
        kafka_task.cancel()
        try:
            await kafka_task
            logger.debug("Kafka consumer task finished gracefully.")
        except asyncio.CancelledError:
            logger.warning("Kafka consumer task was cancelled during shutdown.")
        except Exception as e:
            logger.error(
                f"Error during Kafka consumer task shutdown: {e}", exc_info=True
            )

    # 3. Закрываем соединение с кэшем (Redis)
    await close_cache_connection()
    logger.info("Application shutdown complete.")


# --- Создание Экземпляра FastAPI ---
app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    debug=DEBUG,
    lifespan=lifespan,
    description=f"API для сервиса '{APP_NAME}'. Обрабатывает сообщения Kafka о перемещении товаров и предоставляет информацию о текущих запасах и перемещениях.",
)

# --- Подключение Middleware ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 2. Глобальный Обработчик Исключений:
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    # Логируем ошибку с полным стектрейсом
    logger.error(f"Unhandled exception during request processing: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal Server Error"},
    )


# --- Подключение Роутов ---
app.include_router(api_router, prefix=API_PREFIX)
logger.info(f"API routes included with prefix: {API_PREFIX}")

# --- Подключение Метрик Prometheus ---
metrics_app = make_asgi_app()
# Монтируем его на путь /metrics. Prometheus сможет собирать метрики с этого эндпоинта.
app.mount("/metrics", metrics_app)
logger.info("Prometheus metrics endpoint mounted at /metrics")


# --- Настройка OpenAPI (Swagger UI / ReDoc) ---
def custom_openapi():
    """Генерирует и кэширует OpenAPI схему с кастомными метаданными."""
    if app.openapi_schema:
        return app.openapi_schema

    # Генерируем схему с помощью утилиты FastAPI
    openapi_schema = get_openapi(
        title=f"{APP_NAME} API",
        version=APP_VERSION,
        description=app.description,
        routes=app.routes,
        tags=[
            {
                "name": "Movements",
                "description": "Операции, связанные с перемещениями товаров.",
            },
            {
                "name": "Warehouses",
                "description": "Операции для получения информации о складах.",
            },
        ],
    )
    app.openapi_schema = openapi_schema
    return app.openapi_schema


# Переопределяем стандартный метод генерации OpenAPI схемы FastAPI
app.openapi = custom_openapi
logger.info("Custom OpenAPI schema generation configured.")


# --- Корневой Эндпоинт ---
@app.get("/", include_in_schema=False)
async def root():
    """Простой корневой эндпоинт для проверки работы сервиса."""
    logger.debug("Root endpoint '/' accessed.")
    return {
        "message": f"Welcome to {APP_NAME} v{APP_VERSION}! Docs available at /docs или /redoc"
    }


# --- Точка Входа для Запуска (Локальная разработка) ---
if __name__ == "__main__":
    # Используется для локальной разработки с Uvicorn.
    import uvicorn

    logger.info("Starting application with Uvicorn for local development...")
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=DEBUG)


# --- Получение метрик ---
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    REQUESTS_COUNTER.labels(method=request.method, path=request.url.path).inc()
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    REQUEST_LATENCY.labels(method=request.method, path=request.url.path).observe(
        process_time
    )
    return response
