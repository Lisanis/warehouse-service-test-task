import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import (
    ErrorResponse,
    MovementDetailResponse,
    WarehouseStockResponse,
)
from app.cache.manager import CacheManager, get_cache_manager
from app.db.crud import MovementRepository, WarehouseStockRepository
from app.db.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get(
    "/movements/{movement_id}",
    response_model=MovementDetailResponse,
    summary="Получить информацию о перемещении",
    description="Возвращает детальную информацию о конкретном перемещении товара по его ID, "
    "включая отправителя, получателя, время, прошедшее между отправкой и приемкой "
    "(если перемещение завершено), и разницу в количестве товара.",
    responses={
        200: {"description": "Информация о перемещении найдена."},
        404: {
            "model": ErrorResponse,
            "description": "Перемещение с указанным ID не найдено.",
        },
        500: {"model": ErrorResponse, "description": "Внутренняя ошибка сервера."},
    },
    tags=["Movements"],
)
async def get_movement(
    movement_id: str,
    db: AsyncSession = Depends(get_db),
    cache_manager: CacheManager = Depends(get_cache_manager),
) -> MovementDetailResponse:
    """
    Обрабатывает GET запрос для получения информации о перемещении.
    Сначала проверяет кэш, затем обращается к базе данных.
    Кэширует результат, если он получен из БД.
    """
    cache_key = f"movement:{movement_id}"

    # 1. Попытка получить данные из кэша
    try:
        cached_data = await cache_manager.get(cache_key)
        if cached_data:
            logger.debug(f"Cache hit for movement: {movement_id}")
            return MovementDetailResponse.model_validate(cached_data)
        logger.debug(f"Cache miss for movement: {movement_id}")
    except Exception as e:
        logger.warning(f"Failed to get movement {movement_id} from cache: {e}")

    # 2. Если в кэше нет, получаем данные из базы
    try:
        movement_repo = MovementRepository(db)
        movement = await movement_repo.get_by_id(movement_id)

        if not movement:
            logger.warning(f"Movement with ID {movement_id} not found in DB.")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Movement with ID {movement_id} not found",
            )

        response = MovementDetailResponse.from_db_model(movement)

        # 3. Сохраняем результат в кэш
        try:
            await cache_manager.set(cache_key, response.model_dump())
            logger.debug(f"Movement {movement_id} saved to cache.")
        except Exception as e:
            logger.warning(f"Failed to set movement {movement_id} to cache: {e}")

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving movement {movement_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while retrieving movement information.",
        )


@router.get(
    "/warehouses/{warehouse_id}/products/{product_id}",
    response_model=WarehouseStockResponse,
    summary="Получить остаток товара на складе",
    description="Возвращает информацию о текущем количестве (остатке) "
    "конкретного товара на указанном складе.",
    responses={
        200: {"description": "Информация об остатках найдена."},
        404: {
            "model": ErrorResponse,
            "description": "Остаток для данного товара на складе не найден (возможно, его там никогда не было).",
        },
        500: {"model": ErrorResponse, "description": "Внутренняя ошибка сервера."},
    },
    tags=["Warehouses"],
)
async def get_warehouse_product_stock(
    warehouse_id: str,
    product_id: str,
    db: AsyncSession = Depends(get_db),
    cache_manager: CacheManager = Depends(get_cache_manager),
) -> WarehouseStockResponse:
    """
    Обрабатывает GET запрос для получения остатка товара на складе.
    Сначала проверяет кэш, затем обращается к базе данных.
    Кэширует результат, если он получен из БД.
    """
    cache_key = f"stock:{warehouse_id}:{product_id}"

    # 1. Попытка получить данные из кэша
    try:
        cached_data = await cache_manager.get(cache_key)
        if cached_data:
            logger.debug(f"Cache hit for stock: {warehouse_id}/{product_id}")
            return WarehouseStockResponse.model_validate(cached_data)
        logger.debug(f"Cache miss for stock: {warehouse_id}/{product_id}")
    except Exception as e:
        logger.warning(
            f"Failed to get stock {warehouse_id}/{product_id} from cache: {e}"
        )

    # 2. Если в кэше нет, получаем данные из базы
    try:
        stock_repo = WarehouseStockRepository(db)
        stock = await stock_repo.get_stock(warehouse_id, product_id)

        if not stock:
            logger.warning(
                f"Stock not found for warehouse {warehouse_id}, product {product_id} in DB."
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Stock not found for warehouse {warehouse_id} and product {product_id}",
            )

        response = WarehouseStockResponse.model_validate(stock)

        # 3. Сохраняем результат в кэш
        try:
            await cache_manager.set(cache_key, response.model_dump())
            logger.debug(f"Stock {warehouse_id}/{product_id} saved to cache.")
        except Exception as e:
            logger.warning(
                f"Failed to set stock {warehouse_id}/{product_id} to cache: {e}"
            )

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error retrieving stock for warehouse {warehouse_id}, product {product_id}: {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while retrieving stock information.",
        )
