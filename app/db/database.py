from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from app.config import DATABASE_URL

# Создаем асинхронный "движок" SQLAlchemy для взаимодействия с базой данных.
engine = create_async_engine(DATABASE_URL, echo=True, future=True)

# Создаем фабрику асинхронных сессий. Каждая сессия представляет собой транзакцию.
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# Базовый класс для декларативных моделей SQLAlchemy.
Base = declarative_base()


async def get_db():
    """
    Зависимость FastAPI для получения асинхронной сессии базы данных.

    Создает новую сессию для каждого запроса, обеспечивает её закрытие
    и откат транзакции в случае ошибки.

    Yields:
        AsyncSession: Асинхронная сессия SQLAlchemy.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception as e:
            await session.rollback()
            raise e
        finally:
            await session.close()
