"""Alembic迁移环境配置."""

import asyncio
import os
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from nexus.config import settings
from nexus.db.database import Base

# 导入所有模型，确保Alembic能检测到
import nexus.models  # noqa: F401

# this is the Alembic Config object
config = context.config

# P0 (Task 1.4): 引导式迁移支持 — 第一次部署需要在 nexus superuser 下
# 运行 migration (因为 CREATE ROLE 需要 CREATEROLE 权限, nexus_app 没有)。
# 日常 alembic upgrade head 在 app 容器内执行, 此时 DATABASE_URL 已指向
# nexus_app — 后续迁移都是 schema 变更, 走 nexus superuser 通道不必要。
# 解决方案: 优先读 MIGRATION_DATABASE_URL, 缺省才用 settings.DATABASE_URL。
# 操作员只需在第一次部署时设 MIGRATION_DATABASE_URL, 后续保持空即可。
_migration_url = os.environ.get("MIGRATION_DATABASE_URL") or settings.DATABASE_URL
config.set_main_option("sqlalchemy.url", _migration_url)

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here for 'autogenerate' support
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """In this scenario we need to create an Engine
    and associate a connection with the context.
    """
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
