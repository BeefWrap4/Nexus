"""跨数据库兼容类型.

开发环境(SQLite)使用 JSON/String，生产环境(PostgreSQL)使用 JSONB/UUID/INET。
"""

from sqlalchemy import JSON, String, TypeDecorator
import uuid


class SQLiteUUID(TypeDecorator):
    """跨数据库 UUID 类型：SQLite 存为 String(36)，PostgreSQL 原生 UUID."""
    impl = String(36)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return str(value)
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value
        try:
            return uuid.UUID(str(value))
        except (ValueError, AttributeError):
            return value


JSONVariant = JSON  # 跨数据库 JSON 类型
UUIDVariant = SQLiteUUID  # 跨数据库 UUID 类型
