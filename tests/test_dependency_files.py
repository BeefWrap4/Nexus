from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_REQUIREMENTS = ROOT / "requirements.txt"
DEV_REQUIREMENTS = ROOT / "requirements-dev.txt"


def _requirement_names(path: Path) -> set[str]:
    names: set[str] = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        name = line
        for separator in ("<", ">", "=", "~", "!", "["):
            name = name.split(separator, 1)[0]
        names.add(name.strip().lower())
    return names


def test_runtime_requirements_exclude_dev_and_test_tools():
    runtime_packages = _requirement_names(RUNTIME_REQUIREMENTS)

    assert "pytest" not in runtime_packages
    assert "pytest-asyncio" not in runtime_packages
    assert "pytest-cov" not in runtime_packages
    assert "black" not in runtime_packages
    assert "ruff" not in runtime_packages
    assert "mypy" not in runtime_packages


def test_dev_requirements_extend_runtime_requirements():
    dev_text = DEV_REQUIREMENTS.read_text(encoding="utf-8")
    dev_packages = _requirement_names(DEV_REQUIREMENTS)

    assert "-r requirements.txt" in dev_text
    assert "pytest" in dev_packages
    assert "pytest-asyncio" in dev_packages
    assert "pytest-cov" in dev_packages
    assert "black" in dev_packages
    assert "ruff" in dev_packages
    assert "mypy" in dev_packages
