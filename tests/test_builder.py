"""Workflow engine builder regression tests."""

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
