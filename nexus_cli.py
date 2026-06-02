#!/usr/bin/env python3
"""NEXUS CLI - 开发运维工具.

命令:
    db init      - 初始化数据库（创建表）
    db migrate   - 运行Alembic迁移
    db seed      - 插入种子数据
    run          - 启动FastAPI开发服务器
    worker       - 启动Celery Worker
"""

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

# 加载环境变量
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    load_dotenv(env_path)

# 确保项目根目录在sys.path
project_root = Path(__file__).parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from nexus.config import settings
from nexus.db.database import init_db
from nexus.exceptions import NexusException

console = Console()
app = typer.Typer(
    name="nexus",
    help="NEXUS Enterprise Multi-Agent Orchestration Engine CLI",
    no_args_is_help=True,
)

# DB子命令
db_app = typer.Typer(help="数据库管理命令")
app.add_typer(db_app, name="db")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _run_alembic(args: list[str]) -> int:
    """运行alembic命令，返回退出码."""
    cmd = [sys.executable, "-m", "alembic"] + args
    console.print(f"[dim]Running: {' '.join(cmd)}[/dim]")
    result = subprocess.run(cmd, cwd=str(project_root))
    return result.returncode


async def _async_init_db():
    """异步初始化数据库."""
    await init_db()


# ---------------------------------------------------------------------------
# DB Commands
# ---------------------------------------------------------------------------
@db_app.command("init")
def db_init(
    skip_tables: bool = typer.Option(
        False, "--skip-tables", help="仅测试连接，不创建表"
    ),
):
    """初始化数据库（创建所有表）."""
    console.print("[bold blue]Initializing database...[/bold blue]")
    try:
        if not skip_tables:
            asyncio.run(_async_init_db())
            console.print("[bold green]Database tables created successfully.[/bold green]")
        else:
            # 仅测试连接
            from nexus.db.database import engine

            async def _test():
                from sqlalchemy import text
                async with engine.connect() as conn:
                    await conn.execute(text("SELECT 1"))

            asyncio.run(_test())
            console.print("[bold green]Database connection OK.[/bold green]")
    except Exception as exc:
        console.print(f"[bold red]Database init failed: {exc}[/bold red]")
        raise typer.Exit(1)


@db_app.command("migrate")
def db_migrate(
    revision: str = typer.Option("head", "--rev", "-r", help="目标版本"),
    dry_run: bool = typer.Option(False, "--dry-run", help="仅显示SQL不执行"),
):
    """运行Alembic数据库迁移."""
    console.print(f"[bold blue]Running migrations to {revision}...[/bold blue]")
    args = ["upgrade", revision]
    if dry_run:
        args = ["upgrade", revision, "--sql"]
    rc = _run_alembic(args)
    if rc != 0:
        console.print("[bold red]Migration failed.[/bold red]")
        raise typer.Exit(rc)
    console.print("[bold green]Migrations completed.[/bold green]")


@db_app.command("makemigrations")
def db_makemigrations(
    message: str = typer.Option(..., "--message", "-m", help="迁移说明"),
    autogenerate: bool = typer.Option(True, "--autogenerate/--no-autogenerate"),
):
    """生成新的Alembic迁移脚本."""
    if not message:
        console.print("[bold red]Error: --message is required[/bold red]")
        raise typer.Exit(1)
    args = ["revision", "-m", message]
    if autogenerate:
        args.append("--autogenerate")
    rc = _run_alembic(args)
    if rc != 0:
        raise typer.Exit(rc)


@db_app.command("seed")
def db_seed(
    reset: bool = typer.Option(False, "--reset", help="先清空再插入"),
    fixtures: list[str] = typer.Option(
        None, "--fixture", help="指定要加载的fixture文件"
    ),
):
    """插入种子数据（开发/测试用）."""
    console.print("[bold blue]Seeding database...[/bold blue]")

    async def _seed():
        from nexus.db.database import AsyncSessionLocal
        from nexus.models.tenant import Tenant, User
        from nexus.security.auth import AuthService

        async with AsyncSessionLocal() as session:
            if reset:
                console.print("[yellow]Resetting tables...[/yellow]")
                # 注意：生产环境慎用；这里仅删除非核心表的数据
                from sqlalchemy import text
                await session.execute(text("TRUNCATE TABLE hitl_tasks, wf_runs, node_runs, wf_versions, workflows, agents, tools, api_keys, users, tenants CASCADE"))
                await session.commit()
                console.print("[yellow]Tables truncated.[/yellow]")

            # 创建默认租户
            tenant = Tenant(name="Default Tenant", slug="default", plan="free")
            session.add(tenant)
            await session.flush()  # 获取tenant.id

            # 创建默认管理员用户
            user = User(
                tenant_id=tenant.id,
                email="admin@nexus.local",
                name="Admin",
                role="admin",
                password_hash="$2b$12$placeholder",  # 生产环境应使用bcrypt哈希
            )
            session.add(user)
            await session.commit()

            # 生成JWT token供开发使用
            token = AuthService.create_access_token(
                str(user.id), str(tenant.id), user.role
            )
            console.print(f"[dim]Dev token:[/dim] {token}")

            console.print(
                f"[bold green]Seeded tenant={tenant.id} user={user.id}[/bold green]"
            )

    try:
        asyncio.run(_seed())
    except Exception as exc:
        console.print(f"[bold red]Seed failed: {exc}[/bold red]")
        raise typer.Exit(1)


@db_app.command("status")
def db_status():
    """查看迁移状态."""
    rc = _run_alembic(["current"])
    if rc != 0:
        raise typer.Exit(rc)
    rc = _run_alembic(["history", "--verbose"])
    if rc != 0:
        raise typer.Exit(rc)


# ---------------------------------------------------------------------------
# Run Command
# ---------------------------------------------------------------------------
@app.command("run")
def run_server(
    host: str = typer.Option("0.0.0.0", "--host", "-h", help="绑定地址"),
    port: int = typer.Option(8000, "--port", "-p", help="端口"),
    reload: bool = typer.Option(True, "--reload/--no-reload", help="自动重载"),
    workers: int = typer.Option(1, "--workers", "-w", help="工作进程数（生产环境）"),
    env: str = typer.Option("development", "--env", "-e", help="运行环境"),
):
    """启动FastAPI开发/生产服务器."""
    os.environ["ENVIRONMENT"] = env
    if env == "production":
        reload = False

    cmd = [
        sys.executable, "-m", "uvicorn",
        "nexus.api.main:app",
        "--host", host,
        "--port", str(port),
    ]
    if reload:
        cmd.append("--reload")
    if workers > 1 and not reload:
        cmd.extend(["--workers", str(workers)])

    console.print(f"[bold blue]Starting NEXUS server on {host}:{port} ({env})...[/bold blue]")
    console.print(f"[dim]{' '.join(cmd)}[/dim]")

    try:
        subprocess.run(cmd)
    except KeyboardInterrupt:
        console.print("[bold yellow]Server stopped.[/bold yellow]")


# ---------------------------------------------------------------------------
# Worker Command
# ---------------------------------------------------------------------------
@app.command("worker")
def run_worker(
    name: str = typer.Option("nexus-worker", "--name", "-n", help="Worker名称"),
    concurrency: int = typer.Option(10, "--concurrency", "-c", help="并发数"),
):
    """启动ARQ Worker.

    ARQ 是基于 Redis 的纯异步任务队列，支持:
    - 自动重试（max_tries=3）
    - 延迟执行（defer_by）
    - 任务结果保留（keep_result=3600s）
    """
    try:
        import arq  # noqa: F401
    except ImportError:
        console.print("[bold red]arq is not installed. Run: pip install arq[/bold red]")
        raise typer.Exit(1)

    # 通过环境变量传递并发配置（WorkerSettings 读取）
    os.environ["ARQ_WORKER_CONCURRENCY"] = str(concurrency)

    cmd = [
        sys.executable, "-m", "arq",
        "nexus.jobs.config.WorkerSettings",
    ]

    console.print(f"[bold blue]Starting ARQ worker ({name})...[/bold blue]")
    console.print(f"[dim]Concurrency: {concurrency}[/dim]")
    console.print(f"[dim]{' '.join(cmd)}[/dim]")

    try:
        subprocess.run(cmd)
    except KeyboardInterrupt:
        console.print("[bold yellow]Worker stopped.[/bold yellow]")


# ---------------------------------------------------------------------------
# Info Command
# ---------------------------------------------------------------------------
@app.command("info")
def info():
    """显示NEXUS配置信息."""
    table = Table(title="NEXUS Configuration")
    table.add_column("Key", style="cyan", no_wrap=True)
    table.add_column("Value", style="magenta")

    table.add_row("APP_NAME", settings.APP_NAME)
    table.add_row("APP_VERSION", settings.APP_VERSION)
    table.add_row("ENVIRONMENT", settings.ENVIRONMENT)
    table.add_row("DEBUG", str(settings.DEBUG))
    table.add_row("DATABASE_URL", settings.DATABASE_URL)
    table.add_row("REDIS_URL", settings.REDIS_URL)
    table.add_row("LITELLM_PROXY_URL", settings.LITELLM_PROXY_URL)

    console.print(table)


if __name__ == "__main__":
    app()
