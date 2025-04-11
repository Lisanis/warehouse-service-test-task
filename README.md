# Сервис мониторинга состояния складов

Микросервис на Python, предназначенный для обработки сообщений от складов, которые уведомляют о приемках и отправках товаров. Микросервис сохраняет данные о перемещениях и предоставляет API для получения информации о конкретных перемещениях и текущих состояниях складов.

## Технический стек

- **Язык программирования**: Python 3.11
- **Веб-фреймворк**: FastAPI
- **Брокер сообщений**: Kafka
- **База данных**: PostgreSQL
- **Кэширование**: Redis
- **Мониторинг**: Prometheus + Grafana
- **Контейнеризация**: Docker и Docker Compose

## Функциональность

- Обработка сообщений о приемке и отправке товаров на складах
- Отслеживание перемещений товаров между складами
- Учет текущего количества товаров на складах
- Предоставление API для получения информации о перемещениях и остатках на складах
- Система кэширования для повышения производительности
- Мониторинг состояния сервиса

## API Endpoints

### Получение информации о перемещении
- **URL**: `/api/movements/<movement_id>`
- **Метод**: GET
- **Описание**: Возвращает информацию о перемещении по его ID, включая отправителя, получателя, время, прошедшее между отправкой и приемкой, и разницу в количестве товара.

### Получение информации о состоянии склада
- **URL**: `/api/warehouses/<warehouse_id>/products/<product_id>`
- **Метод**: GET
- **Описание**: Возвращает информацию о текущем запасе товара в конкретном складе.

## Запуск проекта

### Локальное окружение

1. Установите зависимости:
   ```bash
   pip install -r requirements.txt
   ```

2. Запустите сервис:
   ```bash
   uvicorn app.main:app --reload
   ```

### С использованием Docker Compose

1. Запустите все сервисы:
   ```bash
   docker-compose up -d
   ```

2. Запустите применение миграций и обновите базу данных:
    ```bash
    docker-compose exec web alembic upgrade head
    ```

3. Доступ к API:
   - Swagger UI: http://localhost:8000/docs
   - ReDoc: http://localhost:8000/redoc

4. Мониторинг:
   - Prometheus: http://localhost:9090
   - Grafana: http://localhost:3000 (логин/пароль: admin/admin)

## Тестирование

### Запуск тестов:
   ```bash
  docker-compose -f docker-compose.test.yml up -d
   ```
   ```bash
   pytest
   ```

## Разработка

### Установка pre-commit хуков

   ```bash
   pre-commit install
   ```

## Формат сообщений Kafka

### Прибытие товара
```json
{
    "id": "b3b53031-e83a-4654-87f5-b6b6fb09fd99",
    "source": "WH-3423",
    "specversion": "1.0",
    "type": "ru.retail.warehouses.movement",
    "datacontenttype": "application/json",
    "dataschema": "ru.retail.warehouses.movement.v1.0",
    "time": 1737439421623,
    "subject": "WH-3423:ARRIVAL",
    "destination": "ru.retail.warehouses",
    "data": {
        "movement_id": "c6290746-790e-43fa-8270-014dc90e02e0",
        "warehouse_id": "c1d70455-7e14-11e9-812a-70106f431230",
        "timestamp": "2025-02-18T14:34:56Z",
        "event": "arrival",
        "product_id": "4705204f-498f-4f96-b4ba-df17fb56bf55",
        "quantity": 100
    }
}
```

### Отбытие товара
```json
{
    "id": "b3b53031-e83a-4654-87f5-b6b6fb09fd91",
    "source": "WH-3322",
    "specversion": "1.0",
    "type": "ru.retail.warehouses.movement",
    "datacontenttype": "application/json",
    "dataschema": "ru.retail.warehouses.movement.v1.0",
    "time": 1737439421623,
    "subject": "WH-3322:DEPARTURE",
    "destination": "ru.retail.warehouses",
    "data": {
        "movement_id": "c6290746-790e-43fa-8270-014dc90e02e0",
        "warehouse_id": "c1d70455-7e14-11e9-812a-70106f431230",
        "timestamp": "2025-02-18T12:12:56Z",
        "event": "departure",
        "product_id": "4705204f-498f-4f96-b4ba-df17fb56bf55",
        "quantity": 100
    }
}
```
