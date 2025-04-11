from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.crud import WarehouseStockRepository
from app.db.models import WarehouseStock

pytestmark = pytest.mark.asyncio


@pytest.fixture
def mock_db_session() -> AsyncMock:
    """Фикстура для мока AsyncSession."""
    session = AsyncMock(spec=AsyncSession)
    session.execute = AsyncMock()
    session.scalars = MagicMock()
    session.scalar_one_or_none = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    return session


@pytest.fixture
def stock_repo(mock_db_session: AsyncMock) -> WarehouseStockRepository:
    """Фикстура для создания репозитория с мок-сессией."""
    return WarehouseStockRepository(session=mock_db_session)


# --- Тесты для get_stock ---
async def test_get_stock_found(
    stock_repo: WarehouseStockRepository, mock_db_session: AsyncMock
):
    """Тест get_stock, когда запись найдена."""
    # Arrange
    mock_stock = WarehouseStock(warehouse_id="W1", product_id="P1", quantity=10)
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = mock_stock
    mock_db_session.execute.return_value = mock_result

    # Act
    result = await stock_repo.get_stock("W1", "P1")

    # Assert
    assert result == mock_stock
    mock_db_session.execute.assert_called_once()


async def test_get_stock_not_found(
    stock_repo: WarehouseStockRepository, mock_db_session: AsyncMock
):
    """Тест get_stock, когда запись не найдена."""
    # Arrange
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = (
        None  # Имитируем отсутствие результата
    )
    mock_db_session.execute.return_value = mock_result

    # Act
    result = await stock_repo.get_stock("W1", "P1")

    # Assert
    assert result is None
    mock_db_session.execute.assert_called_once()


# --- Тесты для create_or_update_stock ---
async def test_create_or_update_stock_create_new(
    stock_repo: WarehouseStockRepository, mock_db_session: AsyncMock
):
    """Тест создания новой записи остатка."""
    # Arrange
    warehouse_id = "W_NEW"
    product_id = "P_NEW"
    quantity_delta = 50

    mock_get_stock_result = MagicMock()
    mock_get_stock_result.scalars.return_value.first.return_value = None
    mock_db_session.execute.return_value = mock_get_stock_result

    # Act
    result_stock = await stock_repo.create_or_update_stock(
        warehouse_id, product_id, quantity_delta
    )

    # Assert
    mock_db_session.execute.assert_called_once()
    mock_db_session.add.assert_called_once()
    mock_db_session.flush.assert_called_once()
    mock_db_session.refresh.assert_called_once()

    # Проверяем аргументы add и созданный объект
    added_obj = mock_db_session.add.call_args[0][0]
    assert isinstance(added_obj, WarehouseStock)
    assert added_obj.warehouse_id == warehouse_id
    assert added_obj.product_id == product_id
    assert added_obj.quantity == quantity_delta
    assert result_stock == added_obj


async def test_create_or_update_stock_update_existing(
    stock_repo: WarehouseStockRepository, mock_db_session: AsyncMock
):
    """Тест обновления существующей записи остатка."""
    # Arrange
    warehouse_id = "W_EXIST"
    product_id = "P_EXIST"
    initial_quantity = 100
    quantity_delta = -20

    mock_existing_stock = WarehouseStock(
        warehouse_id=warehouse_id, product_id=product_id, quantity=initial_quantity
    )

    mock_get_stock_result = MagicMock()
    mock_get_stock_result.scalars.return_value.first.return_value = mock_existing_stock
    mock_db_session.execute.return_value = mock_get_stock_result

    # Act
    result_stock = await stock_repo.create_or_update_stock(
        warehouse_id, product_id, quantity_delta
    )

    # Assert
    mock_db_session.execute.assert_called_once()
    mock_db_session.add.assert_not_called()
    mock_db_session.flush.assert_called_once()
    mock_db_session.refresh.assert_called_once()

    # Проверяем обновленное количество и возвращенный объект
    assert mock_existing_stock.quantity == initial_quantity + quantity_delta
    assert result_stock == mock_existing_stock


async def test_create_or_update_stock_raises_error_on_negative_create(
    stock_repo: WarehouseStockRepository, mock_db_session: AsyncMock
):
    """Тест: ошибка при попытке СОЗДАТЬ запись с отрицательным количеством."""
    # Arrange
    mock_get_stock_result = MagicMock()
    mock_get_stock_result.scalars.return_value.first.return_value = None
    mock_db_session.execute.return_value = mock_get_stock_result

    # Act & Assert
    with pytest.raises(
        ValueError, match="Cannot initialize stock with negative quantity"
    ):
        await stock_repo.create_or_update_stock("W_NEG", "P_NEG", -10)

    mock_db_session.add.assert_not_called()


async def test_create_or_update_stock_raises_error_on_negative_update(
    stock_repo: WarehouseStockRepository, mock_db_session: AsyncMock
):
    """Тест: ошибка при попытке ОБНОВИТЬ запись до отрицательного количества."""
    # Arrange
    initial_quantity = 10
    mock_existing_stock = WarehouseStock(
        warehouse_id="W_NEG", product_id="P_NEG", quantity=initial_quantity
    )
    mock_get_stock_result = MagicMock()
    mock_get_stock_result.scalars.return_value.first.return_value = mock_existing_stock
    mock_db_session.execute.return_value = mock_get_stock_result

    # Act & Assert
    with pytest.raises(ValueError, match="Cannot reduce stock below zero"):
        await stock_repo.create_or_update_stock(
            "W_NEG", "P_NEG", -(initial_quantity + 1)
        )

    mock_db_session.flush.assert_not_called()
    mock_db_session.refresh.assert_not_called()
