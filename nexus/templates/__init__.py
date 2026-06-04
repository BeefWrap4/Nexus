"""NEXUS Agent Templates — pre-built industry solutions."""
import json
import os
from pathlib import Path

_TEMPLATES_DIR = Path(__file__).parent


def list_templates() -> list[dict]:
    """列出所有可用模板."""
    templates = []
    for f in _TEMPLATES_DIR.glob("*.json"):
        with open(f) as fp:
            templates.append(json.load(fp))
    return templates


def get_template(name: str) -> dict | None:
    """获取指定模板."""
    path = _TEMPLATES_DIR / f"{name}.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return None
