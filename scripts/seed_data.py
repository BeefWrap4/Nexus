#!/usr/bin/env python3
"""NEXUS 种子数据脚本.

用法:
    python scripts/seed_data.py [--reset] [--fixture fixtures/demo.json]

功能:
    - 创建默认租户 (Default Tenant)
    - 创建默认管理员用户 (admin@nexus.local)
    - 创建示例工作流、Agent、工具配置
    - 支持通过 --reset 清空现有数据后重新插入
    - 支持加载自定义 fixture JSON 文件
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

# 将项目根目录加入 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

# 加载环境变量
env_path = PROJECT_ROOT / ".env"
if env_path.exists():
    load_dotenv(env_path)

from nexus.db.database import AsyncSessionLocal, close_db, init_db
from nexus.models import Agent, Tenant, Tool, User, Workflow
from nexus.security.auth import AuthService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


async def reset_data(session):
    """清空所有业务数据表（保留结构）."""
    from sqlalchemy import text

    logger.warning("Truncating all data tables...")
    tables = [
        "artifacts",
        "audit_logs",
        "hitl_tasks",
        "node_runs",
        "wf_runs",
        "wf_versions",
        "workflows",
        "agents",
        "tools",
        "api_keys",
        "users",
        "tenants",
    ]
    for table in tables:
        await session.execute(text(f"TRUNCATE TABLE {table} CASCADE"))
    await session.commit()
    logger.info("All tables truncated.")


async def seed_default_tenant(session) -> Tenant:
    """创建默认租户."""
    tenant = Tenant(
        id=uuid4(),
        name="Default Tenant",
        slug="default",
        plan="free",
        status="active",
    )
    session.add(tenant)
    await session.flush()
    logger.info(f"Created tenant: {tenant.name} (id={tenant.id})")
    return tenant


async def seed_admin_user(session, tenant_id: str) -> User:
    """创建默认管理员用户."""
    # 使用 bcrypt 生成密码哈希 (密码: admin123)
    import bcrypt

    password = "admin123"
    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    user = User(
        id=uuid4(),
        tenant_id=tenant_id,
        email="admin@nexus.local",
        name="System Administrator",
        role="admin",
        password_hash=password_hash,
        is_active=True,
    )
    session.add(user)
    await session.flush()

    # 生成开发用 JWT Token
    token = AuthService.create_access_token(
        user_id=str(user.id),
        tenant_id=str(tenant_id),
        role=user.role,
    )
    logger.info(f"Created admin user: {user.email} (id={user.id})")
    logger.info(f"Admin password: {password}")
    logger.info(f"Dev JWT Token: {token}")
    return user


async def seed_sample_agents(session, tenant_id: str) -> list[Agent]:
    """创建示例 Agent 配置."""
    agents_data = [
        {
            "name": "Data Analyst",
            "role": "Senior Data Analyst",
            "goal": "Analyze business data and extract actionable insights",
            "backstory": "You are an experienced data analyst with expertise in SQL, Python, and business intelligence.",
            "model_config": {
                "provider": "openai",
                "model": "gpt-4o",
                "temperature": 0.3,
                "max_tokens": 4000,
            },
            "system_prompt": "You are a data analyst. Always provide data-backed insights with clear visualizations when possible.",
            "tools": ["sql_query", "python_executor", "chart_generator"],
            "max_iterations": 10,
        },
        {
            "name": "Code Reviewer",
            "role": "Senior Software Engineer",
            "goal": "Review code for quality, security, and best practices",
            "backstory": "You are a senior engineer with 15 years of experience in software architecture and code review.",
            "model_config": {
                "provider": "openai",
                "model": "gpt-4o",
                "temperature": 0.2,
                "max_tokens": 4000,
            },
            "system_prompt": "You are a code reviewer. Focus on security, performance, maintainability, and adherence to best practices.",
            "tools": ["static_analysis", "security_scanner"],
            "max_iterations": 5,
        },
        {
            "name": "Customer Support",
            "role": "Customer Support Specialist",
            "goal": "Provide helpful and empathetic customer support",
            "backstory": "You are a friendly customer support specialist who always puts the customer first.",
            "model_config": {
                "provider": "openai",
                "model": "gpt-4o-mini",
                "temperature": 0.7,
                "max_tokens": 2000,
            },
            "system_prompt": "You are a customer support agent. Be empathetic, clear, and solution-oriented.",
            "tools": ["knowledge_base", "ticket_search"],
            "max_iterations": 5,
        },
    ]

    agents = []
    for data in agents_data:
        agent = Agent(
            id=uuid4(),
            tenant_id=tenant_id,
            **data,
        )
        session.add(agent)
        agents.append(agent)

    await session.flush()
    logger.info(f"Created {len(agents)} sample agents")
    return agents


async def seed_sample_tools(session, tenant_id: str) -> list[Tool]:
    """创建示例工具配置."""
    tools_data = [
        {
            "name": "sql_query",
            "description": "Execute SQL queries against the database",
            "type": "sql",
            "config": {
                "connection": "${DATABASE_URL}",
                "timeout": 30,
                "max_rows": 10000,
            },
            "schema": {
                "input": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "SQL query to execute"},
                        "params": {"type": "object", "description": "Query parameters"},
                    },
                    "required": ["query"],
                },
                "output": {
                    "type": "object",
                    "properties": {
                        "rows": {"type": "array"},
                        "columns": {"type": "array"},
                        "row_count": {"type": "integer"},
                    },
                },
            },
        },
        {
            "name": "http_request",
            "description": "Make HTTP requests to external APIs",
            "type": "http",
            "config": {
                "timeout": 30,
                "max_retries": 3,
                "follow_redirects": True,
            },
            "schema": {
                "input": {
                    "type": "object",
                    "properties": {
                        "method": {"type": "string", "enum": ["GET", "POST", "PUT", "DELETE", "PATCH"]},
                        "url": {"type": "string"},
                        "headers": {"type": "object"},
                        "body": {"type": "object"},
                    },
                    "required": ["method", "url"],
                },
                "output": {
                    "type": "object",
                    "properties": {
                        "status_code": {"type": "integer"},
                        "headers": {"type": "object"},
                        "body": {"type": "object"},
                    },
                },
            },
        },
        {
            "name": "python_executor",
            "description": "Execute Python code in a sandboxed environment",
            "type": "python",
            "config": {
                "timeout": 60,
                "memory_limit": "256MB",
                "allowed_modules": ["json", "re", "math", "statistics", "datetime", "collections"],
            },
            "schema": {
                "input": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string", "description": "Python code to execute"},
                        "input_data": {"type": "object", "description": "Input variables"},
                    },
                    "required": ["code"],
                },
                "output": {
                    "type": "object",
                    "properties": {
                        "stdout": {"type": "string"},
                        "result": {"type": "object"},
                        "execution_time": {"type": "number"},
                    },
                },
            },
        },
    ]

    tools = []
    for data in tools_data:
        tool = Tool(
            id=uuid4(),
            tenant_id=tenant_id,
            **data,
        )
        session.add(tool)
        tools.append(tool)

    await session.flush()
    logger.info(f"Created {len(tools)} sample tools")
    return tools


async def seed_sample_workflow(session, tenant_id: str, user_id: str) -> Workflow:
    """创建示例工作流."""
    workflow = Workflow(
        id=uuid4(),
        tenant_id=tenant_id,
        created_by=user_id,
        name="Customer Onboarding",
        description="Automated customer onboarding workflow with data enrichment and welcome email",
        status="active",
        config={
            "nodes": [
                {"id": "start", "type": "start", "next": ["enrich_data"]},
                {
                    "id": "enrich_data",
                    "type": "agent",
                    "agent": "Data Analyst",
                    "prompt": "Enrich customer profile with additional data",
                    "next": ["send_welcome"],
                },
                {
                    "id": "send_welcome",
                    "type": "tool",
                    "tool": "http_request",
                    "config": {"method": "POST", "url": "/api/welcome-email"},
                    "next": ["end"],
                },
                {"id": "end", "type": "end"},
            ],
            "edges": [
                {"from": "start", "to": "enrich_data"},
                {"from": "enrich_data", "to": "send_welcome"},
                {"from": "send_welcome", "to": "end"},
            ],
        },
        variables={
            "customer_email": {"type": "string", "required": True},
            "customer_name": {"type": "string", "required": True},
        },
        tags=["onboarding", "customer"],
    )
    session.add(workflow)
    await session.flush()
    logger.info(f"Created sample workflow: {workflow.name} (id={workflow.id})")
    return workflow


async def load_fixture(session, fixture_path: Path):
    """从 JSON fixture 文件加载数据."""
    logger.info(f"Loading fixture: {fixture_path}")
    with open(fixture_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 支持多种 fixture 格式
    if isinstance(data, list):
        for item in data:
            await _load_fixture_item(session, item)
    elif isinstance(data, dict) and "fixtures" in data:
        for item in data["fixtures"]:
            await _load_fixture_item(session, item)
    else:
        await _load_fixture_item(session, data)

    logger.info("Fixture loaded successfully.")


async def _load_fixture_item(session, item: dict):
    """加载单个 fixture 项."""
    model_name = item.get("model")
    fields = item.get("fields", {})

    if model_name == "tenant":
        obj = Tenant(id=uuid4(), **fields)
    elif model_name == "user":
        obj = User(id=uuid4(), **fields)
    elif model_name == "agent":
        obj = Agent(id=uuid4(), **fields)
    elif model_name == "tool":
        obj = Tool(id=uuid4(), **fields)
    elif model_name == "workflow":
        obj = Workflow(id=uuid4(), **fields)
    else:
        logger.warning(f"Unknown model: {model_name}, skipping.")
        return

    session.add(obj)


async def main():
    parser = argparse.ArgumentParser(description="NEXUS Database Seeding")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Truncate all tables before seeding",
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        help="Path to a JSON fixture file to load",
    )
    parser.add_argument(
        "--skip-defaults",
        action="store_true",
        help="Skip default seed data, only load fixtures",
    )
    args = parser.parse_args()

    # 确保表已创建
    logger.info("Ensuring database tables exist...")
    await init_db()

    async with AsyncSessionLocal() as session:
        try:
            if args.reset:
                confirm = input(
                    "WARNING: This will DELETE ALL DATA. Are you sure? [yes/no]: "
                )
                if confirm.lower() != "yes":
                    logger.info("Aborted.")
                    return
                await reset_data(session)

            if not args.skip_defaults:
                tenant = await seed_default_tenant(session)
                user = await seed_admin_user(session, tenant.id)
                await seed_sample_agents(session, tenant.id)
                await seed_sample_tools(session, tenant.id)
                await seed_sample_workflow(session, tenant.id, user.id)

            if args.fixture:
                if not args.fixture.exists():
                    logger.error(f"Fixture file not found: {args.fixture}")
                    raise SystemExit(1)
                await load_fixture(session, args.fixture)

            await session.commit()
            logger.info("Database seeding completed successfully.")

        except Exception as exc:
            await session.rollback()
            logger.error(f"Seeding failed: {exc}")
            raise SystemExit(1)
        finally:
            await close_db()


if __name__ == "__main__":
    asyncio.run(main())
