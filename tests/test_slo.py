"""Verify SLO module + burn rate alert rules."""
import os
import re

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_slo_targets_are_reasonable():
    from nexus.observability.slo import (
        API_SLO_AVAILABILITY,
        API_SLO_LATENCY_P99_MS,
        API_SLO_ERROR_RATE,
    )
    assert 0.99 <= API_SLO_AVAILABILITY <= 0.9999
    assert 100 <= API_SLO_LATENCY_P99_MS <= 5000
    assert 0.0001 <= API_SLO_ERROR_RATE <= 0.01


def test_slo_burn_rate_alert_file_exists():
    path = os.path.join(REPO_ROOT, "monitoring", "alerts", "slo_burn_rate.yml")
    assert os.path.exists(path), "SLO burn rate alert file missing"


def test_slo_burn_rate_alerts_reference_nexus_metrics():
    import yaml

    path = os.path.join(REPO_ROOT, "monitoring", "alerts", "slo_burn_rate.yml")
    if not os.path.exists(path):
        pytest.skip("SLO alert file missing")

    with open(path) as f:
        content = f.read()

    # Strip the Prometheus-emitted suffixes (_bucket/_sum/_count) so that
    # histogram-based alert expressions resolve to the base metric name that
    # is actually defined in metrics.py.
    def _base(name: str) -> str:
        for suffix in ("_bucket", "_sum", "_count"):
            if name.endswith(suffix):
                return name[: -len(suffix)]
        return name

    metrics = {_base(m) for m in re.findall(r"\bnexus_[a-z_0-9]+", content)}
    assert metrics, "SLO alerts reference no nexus_ metrics"

    # All should be real metrics defined in metrics.py
    metrics_path = os.path.join(REPO_ROOT, "nexus", "observability", "metrics.py")
    with open(metrics_path) as f:
        code = f.read()

    for m in metrics:
        assert m in code, f"SLO alert references undefined metric: {m}"
