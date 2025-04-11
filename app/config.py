import os

from dotenv import load_dotenv

load_dotenv()

# Application settings
APP_NAME = "Warehouse Monitoring Service"
APP_VERSION = "1.0.0"
API_PREFIX = "/api"
DEBUG = os.getenv("DEBUG", "False").lower() == "true"

# Database settings
DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@db:5432/warehouse_db"
)

# Kafka settings
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "warehouse_movements")
KAFKA_GROUP_ID = os.getenv("KAFKA_GROUP_ID", "warehouse_service_group")

# Redis Cache settings
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_DB = int(os.getenv("REDIS_DB", 0))
CACHE_TTL = int(os.getenv("CACHE_TTL", 3600))
