from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Movement, Product, Warehouse

pytestmark = pytest.mark.asyncio


async def test_get_movement_success(
    client: AsyncClient,
    db_session: AsyncSession,
    sample_product: Product,
    sample_warehouse: Warehouse,
):
    """Тест успешного получения информации о перемещении (200 OK)."""
    # Arrange: Создаем перемещение в БД
    dest_warehouse = Warehouse(id="W2")
    db_session.add(dest_warehouse)
    await db_session.flush()

    now = datetime.now(timezone.utc)
    movement = Movement(
        id="c6290746-790e-43fa-8270-014dc90e02e1",
        product_id=sample_product.id,
        source_warehouse_id=sample_warehouse.id,
        destination_warehouse_id=dest_warehouse.id,
        departure_timestamp=now - timedelta(hours=1),
        arrival_timestamp=now,
        departure_quantity=50,
        arrival_quantity=49,
        transfer_time=3600.0,
        quantity_difference=-1,
    )
    db_session.add(movement)
    await db_session.commit()

    # Act: Делаем запрос
    response = await client.get(f"/api/movements/{movement.id}")

    # Assert: Проверяем ответ
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == movement.id
    assert data["product_id"] == sample_product.id
    assert data["source_warehouse_id"] == sample_warehouse.id
    assert data["destination_warehouse_id"] == dest_warehouse.id
    assert data["departure_quantity"] == 50
    assert data["arrival_quantity"] == 49
    assert data["transfer_time"] == 3600.0
    assert data["quantity_difference"] == -1
    assert "departure_timestamp" in data
    assert "arrival_timestamp" in data


async def test_get_movement_not_found(client: AsyncClient):
    """Тест получения несуществующего перемещения (404 Not Found)."""
    # Act: Делаем запрос с несуществующим ID
    response = await client.get("/api/movements/NON_EXISTENT_ID")

    # Assert: Проверяем статус и сообщение об ошибке
    print(response.json())
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()
