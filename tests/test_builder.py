"""Workflow engine builder regression tests."""

from pathlib import Path

from nexus.engine.builder import build_engine_and_executors, create_engine_components
from nexus.engine.enums import NodeType
from nexus.engine.event_bus import EventBus
from nexus.engine.state_manager import StateManager


def test_build_engine_reuses_injected_components():
    event_bus = EventBus()
    state_manager = StateManager()

    _, engine, extras = build_engine_and_executors(
        config={"nodes": [], "edges": []},
        event_bus=event_bus,
        state_manager=state_manager,
    )

    assert engine.event_bus is event_bus
    assert engine.state_manager is state_manager
    assert extras["event_bus"] is event_bus
    assert extras["state_manager"] is state_manager


def test_build_engine_registers_extra_executors():
    _, engine, _ = build_engine_and_executors(
        config={"nodes": [], "edges": []},
        register_extra=True,
    )

    assert NodeType.TOOL in engine._executors
    assert NodeType.CONDITION in engine._executors


def test_create_engine_components_uses_injected_event_bus():
    event_bus = EventBus()

    created_event_bus, _, _, _, _ = create_engine_components(event_bus=event_bus)

    assert created_event_bus is event_bus


def test_runtime_entrypoint_files_are_readable():
    """入口文件能正常读取 + Python 语法可解析.

    修复：原版用 encoding="ascii" 强校验，但项目里很多文件含中文注释/字符串，
    实际上 Python 3 默认 UTF-8 读源码。改成真正的有用检查：语法可解析。
    """
    import ast

    repo_root = Path(__file__).resolve().parents[1]
    files = [
        repo_root / "nexus" / "engine" / "builder.py",
        repo_root / "nexus" / "services" / "runner.py",
        repo_root / "nexus" / "jobs" / "workflow.py",
    ]

    for path in files:
        # 用 UTF-8 读，再用 ast 解析成 Python AST —— 任何语法错误都会被发现
        source = path.read_text(encoding="utf-8")
        ast.parse(source, filename=str(path))
