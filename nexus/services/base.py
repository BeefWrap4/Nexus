"""Service基类 - 封装通用CRUD操作.

所有Service继承此类，获得标准的CRUD能力。
使用async SQLAlchemy ORM操作。
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.database import AsyncSessionLocal


ModelType = TypeVar("ModelType")


class BaseService(Generic[ModelType]):
    """Service基类，提供通用CRUD操作."""

    def __init__(self, model_class: type[ModelType]):
        self.model_class = model_class

    async def _get_session(self) -> AsyncSession:
        """获取新的数据库会话（用于Service内部使用）."""
        return AsyncSessionLocal()

    async def create(
        self,
        session: AsyncSession,
        data: dict[str, Any],
        tenant_id: UUID,
        user_id: UUID | None = None,
    ) -> ModelType:
        """创建记录.

        Args:
            session: 数据库会话
            data: 创建数据
            tenant_id: 租户ID
            user_id: 用户ID（可选）

        Returns:
            创建的记录实例
        """
        db_data = dict(data)
        db_data["tenant_id"] = tenant_id
        if user_id is not None and hasattr(self.model_class, "created_by"):
            db_data["created_by"] = user_id

        instance = self.model_class(**db_data)
        session.add(instance)
        await session.flush()
        await session.refresh(instance)
        await session.commit()
        return instance

    async def get(
        self,
        session: AsyncSession,
        id: UUID,
        tenant_id: UUID,
    ) -> ModelType | None:
        """根据ID获取记录.

        Args:
            session: 数据库会话
            id: 记录ID
            tenant_id: 租户ID

        Returns:
            记录实例，不存在则返回None
        """
        stmt = select(self.model_class).where(
            self.model_class.id == id,
            self.model_class.tenant_id == tenant_id,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def list(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        skip: int = 0,
        limit: int = 100,
        filters: dict[str, Any] | None = None,
    ) -> tuple[list[ModelType], int]:
        """分页列表查询.

        Args:
            session: 数据库会话
            tenant_id: 租户ID
            skip: 偏移量
            limit: 每页数量
            filters: 额外过滤条件

        Returns:
            (记录列表, 总数量)
        """
        where_clauses = [self.model_class.tenant_id == tenant_id]

        if filters:
            for key, value in filters.items():
                if hasattr(self.model_class, key) and value is not None:
                    where_clauses.append(getattr(self.model_class, key) == value)

        # 查询总数
        count_stmt = select(func.count()).select_from(self.model_class).where(*where_clauses)
        total_result = await session.execute(count_stmt)
        total = total_result.scalar() or 0

        # 查询数据
        stmt = (
            select(self.model_class)
            .where(*where_clauses)
            .offset(skip)
            .limit(limit)
        )
        result = await session.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    async def update(
        self,
        session: AsyncSession,
        id: UUID,
        data: dict[str, Any],
        tenant_id: UUID,
    ) -> ModelType | None:
        """更新记录.

        Args:
            session: 数据库会话
            id: 记录ID
            data: 更新数据
            tenant_id: 租户ID

        Returns:
            更新后的记录实例，不存在则返回None
        """
        instance = await self.get(session, id, tenant_id)
        if instance is None:
            return None

        for key, value in data.items():
            if hasattr(instance, key) and value is not None:
                setattr(instance, key, value)

        session.add(instance)
        await session.flush()
        await session.refresh(instance)
        await session.commit()
        return instance

    async def delete(
        self,
        session: AsyncSession,
        id: UUID,
        tenant_id: UUID,
    ) -> bool:
        """删除记录.

        Args:
            session: 数据库会话
            id: 记录ID
            tenant_id: 租户ID

        Returns:
            是否删除成功
        """
        instance = await self.get(session, id, tenant_id)
        if instance is None:
            return False

        await session.delete(instance)
        await session.flush()
        await session.commit()
        return True
