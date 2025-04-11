import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Product, Warehouse, WarehouseStock

pytestmark = pytest.mark.asyncio


async def test_get_warehouse_stock_success(
    client: AsyncClient,
    db_session: AsyncSession,
    sample_product: Product,
    sample_warehouse: Warehouse,
):
    """Тест успешного получения остатка товара (200 OK)."""
    # Arrange: Создаем запись об остатке
    print(sample_warehouse, "FDA")
    stock = WarehouseStock(
        warehouse_id=sample_warehouse.id, product_id=sample_product.id, quantity=100
    )
    db_session.add(stock)
    await db_session.commit()
    # Act: Делаем запрос к API
    response = await client.get(
        f"/api/warehouses/{stock.warehouse_id}/products/{stock.product_id}"
    )

    # Assert: Проверяем результат
    assert response.status_code == 200
    data = response.json()
    assert data["warehouse_id"] == sample_warehouse.id
    assert data["product_id"] == sample_product.id
    assert data["quantity"] == 100


async def test_get_warehouse_stock_not_found(
    client: AsyncClient,
    db_session: AsyncSession,
    sample_product: Product,
    sample_warehouse: Warehouse,
):
    """Тест получения остатка, когда его нет (404 Not Found)."""
    # Arrange: Убеждаемся, что записи нет (фикстура db_session откатит все)

    # Act: Делаем запрос к API
    response = await client.get(
        f"/api/warehouses/{sample_warehouse.id}/products/{sample_product.id}"
    )

    # Assert: Проверяем результат
    assert response.status_code == 404
    data = response.json()
    assert "not found" in data["detail"].lower()


async def test_get_warehouse_stock_caching(
    client: AsyncClient,
    db_session: AsyncSession,
    test_redis_client,
    sample_product: Product,
    sample_warehouse: Warehouse,
):
    """Тест кэширования остатка товара."""
    # Arrange: Создаем остаток
    stock_quantity = 55
    stock = WarehouseStock(
        warehouse_id="W_CACHE", product_id="P_CACHE", quantity=stock_quantity
    )
    warehouse = Warehouse(id="W_CACHE")
    product = Product(id="P_CACHE")
    db_session.add_all([warehouse, product, stock])
    await db_session.commit()
    cache_key = f"stock:W_CACHE:P_CACHE"

    # Убедимся, что в кэше пусто
    assert await test_redis_client.get(cache_key) is None

    # Act 1: Первый запрос (должен попасть в БД и записать в кэш)
    response1 = await client.get("/api/warehouses/W_CACHE/products/P_CACHE")

    # Assert 1: Проверяем ответ и наличие в кэше
    assert response1.status_code == 200
    assert response1.json()["quantity"] == stock_quantity
    cached_value_str = await test_redis_client.get(cache_key)
    assert cached_value_str is not None
    # Проверяем, что значение в кеше соответствует (учитываем JSON-сериализацию)
    import json

    assert json.loads(cached_value_str)["quantity"] == stock_quantity

    # Act 2: Второй запрос (должен взять из кэша)
    # Можно было бы замокать репозиторий, но для простоты проверим ответ
    response2 = await client.get("/api/warehouses/W_CACHE/products/P_CACHE")

    # Assert 2: Проверяем второй ответ
    assert response2.status_code == 200
    assert response2.json()["quantity"] == stock_quantity
