#!/usr/bin/env python3
"""NEXUS 数据库初始化脚本.

用法:
    python scripts/init_db.py [--drop]

功能:
    - 创建所有数据库表 (SQLAlchemy Base.metadata.create_all)
    - 可选: 先删除所有表再重建 (--drop)
    - 支持通过环境变量或 .env 文件配置数据库连接
"""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

# 将项目根目录加入 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

# 加载环境变量
env_path = PROJECT_ROOT / ".env"
if env_path.exists():
    load_dotenv(env_path)

from sqlalchemy import text

from nexus.db.database import Base, close_db, engine, init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


async def drop_all_tables():
    """删除所有表（慎用，生产环境勿用）."""
    logger.warning("Dropping all tables...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    logger.info("All tables dropped.")


async def create_all_tables():
    """创建所有表."""
    logger.info("Creating all tables...")
    await init_db()
    logger.info("All tables created successfully.")


async def verify_connection():
    """验证数据库连接."""
    logger.info("Verifying database connection...")
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT 1"))
        row = result.scalar()
        if row == 1:
            logger.info("Database connection verified.")
        else:
            raise RuntimeError("Database connection check failed.")


async def main():
    parser = argparse.ArgumentParser(description="NEXUS Database Initialization")
    parser.add_argument(
        "--drop",
        action="store_true",
        help="Drop all tables before creating (DANGEROUS)",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Only check database connection, do not create tables",
    )
    args = parser.parse_args()

    db_url = os.getenv("DATABASE_URL", "postgresql+asyncpg://nexus:nexus@localhost:5432/nexus")
    logger.info(f"Database URL: {db_url.replace('://', '://***:***@')}")

    try:
        await verify_connection()

        if args.check_only:
            logger.info("Connection check passed. Exiting.")
            return

        if args.drop:
            confirm = input(
                "WARNING: This will DROP ALL TABLES. Are you sure? [yes/no]: "
            )
            if confirm.lower() != "yes":
                logger.info("Aborted.")
                return
            await drop_all_tables()

        await create_all_tables()
        logger.info("Database initialization completed successfully.")

    except Exception as exc:
        logger.error(f"Database initialization failed: {exc}")
        raise SystemExit(1)
    finally:
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
