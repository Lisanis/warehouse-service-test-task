import uuid
from typing import AsyncGenerator

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy import NullPool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.cache.manager import CacheManager, get_cache_manager
from app.db.database import Base, get_db
from app.db.models import Movement, Product, Warehouse, WarehouseStock
from app.main import app

TEST_DATABASE_URL = (
    "postgresql+asyncpg://postgres:postgres@localhost:5433/test_postgres"
)


# --- Фикстуры для Тестовой Базы Данных ---
@pytest.fixture(scope="session")
async def test_db_engine():
    """Создает асинхронный движок для тестовой БД."""
    engine = create_async_engine(
        TEST_DATABASE_URL, echo=True, future=True, poolclass=NullPool
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture(scope="function")
async def db_session(test_db_engine) -> AsyncGenerator[AsyncSession, None]:
    """Предоставляет сессию БД для теста с автоматическим откатом."""
    TestSessionLocal = async_sessionmaker(
        bind=test_db_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with TestSessionLocal() as session:
        await session.begin_nested()
        yield session
        await session.rollback()
        await session.close()


# --- Фикстуры для Тестового Кэша (Redis) ---
@pytest.fixture(scope="function")
async def test_redis_client() -> AsyncGenerator[Redis, None]:
    client = Redis(host="localhost", port=6380, db=0, decode_responses=True)
    await client.ping()
    yield client
    await client.flushdb()
    await client.aclose()


@pytest.fixture(scope="function")
async def test_cache_manager(test_redis_client) -> CacheManager:
    """Создает экземпляр CacheManager с тестовым клиентом Redis."""
    cache_manager = CacheManager()
    cache_manager.redis_client = test_redis_client
    cache_manager.ttl = 60
    return cache_manager


# --- Фикстура для Клиента FastAPI ---
@pytest.fixture(scope="function")
async def client(
    db_session: AsyncSession, test_cache_manager: CacheManager
) -> AsyncGenerator[AsyncClient, None]:
    """
    Предоставляет AsyncClient для взаимодействия с FastAPI приложением,
    переопределяя зависимости для использования тестовой БД и кэша.
    """

    def override_get_db_session() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    def override_get_test_cache_manager() -> CacheManager:
        return test_cache_manager

    app.dependency_overrides[get_db] = override_get_db_session
    app.dependency_overrides[get_cache_manager] = override_get_test_cache_manager

    # Создаем тестовый клиент
    async with AsyncClient(app=app, base_url="http://test") as test_client:
        yield test_client
    app.dependency_overrides.clear()


# --- Пример фикстуры для создания тестовых данных (опционально) ---
@pytest.fixture(scope="function")
async def sample_product(db_session: AsyncSession) -> Product:
    product_id = str(uuid.uuid4())
    product = Product(id=product_id)
    db_session.add(product)
    await db_session.commit()
    await db_session.refresh(product)
    return product


@pytest.fixture(scope="function")
async def sample_warehouse(db_session: AsyncSession) -> Warehouse:
    warehouse = str(uuid.uuid4())
    warehouse = Warehouse(id=warehouse)
    db_session.add(warehouse)
    await db_session.commit()
    await db_session.refresh(warehouse)
    return warehouse
