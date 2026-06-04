import subprocess
import sys


def test_requests_dependency_stack_is_compatible():
    result = subprocess.run(
        [sys.executable, "-W", "always", "-c", "import requests"],
        capture_output=True,
        text=True,
        check=True,
    )

    assert "RequestsDependencyWarning" not in result.stderr


def test_fastapi_testclient_stack_is_compatible():
    result = subprocess.run(
        [sys.executable, "-W", "always", "-c", "import fastapi.testclient"],
        capture_output=True,
        text=True,
        check=True,
    )

    assert "StarletteDeprecationWarning" not in result.stderr
