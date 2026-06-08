"""Validate that all alert rule metric names exist in the code.

Prevents the bug class where alert rules referenced deprecated
metric names (e.g. ``http_requests_total`` instead of
``nexus_api_requests_total``) and silently never fired in
production.
"""
import os
import re

import pytest
import yaml

# tests/test_monitoring.py → nexus/
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ALERTS_PATH = os.path.join(REPO_ROOT, "monitoring/alerts/nexus_alerts.yml")
METRICS_PATHS = [
    os.path.join(REPO_ROOT, "nexus/observability/metrics.py"),
    os.path.join(REPO_ROOT, "nexus/observability/agent_metrics.py"),
    os.path.join(REPO_ROOT, "nexus/observability/queue_metrics.py"),
    os.path.join(REPO_ROOT, "nexus/observability/workflow_metrics.py"),
]

# Prometheus auto-suffixes these on Histogram/Summary types. Strip
# them before searching the source so we match the base metric name
# the developer actually defined.
_PROMETHEUS_SUFFIXES = ("_bucket", "_count", "_sum")


def _collect_referenced_metrics(alerts_text: str) -> set:
    """Return every ``nexus_*`` metric name referenced in alert rules."""
    referenced: set = set()
    alerts = yaml.safe_load(alerts_text) or {}
    for group in alerts.get("groups", []):
        for rule in group.get("rules", []):
            expr = rule.get("expr", "")
            for m in re.findall(r"\bnexus_[a-z_0-9]+", expr):
                referenced.add(m)
    return referenced


def _metric_defined_in_code(metric_name: str, metrics_code: str) -> bool:
    """A metric is "defined" if any metrics module declares it as the base name.

    Strips Prometheus suffixes (``_bucket``/``_count``/``_sum``) so a
    Histogram defined as ``nexus_api_request_duration_seconds``
    still satisfies a rule that references the auto-generated
    ``nexus_api_request_duration_seconds_bucket``.
    """
    candidates = [metric_name]
    for suffix in _PROMETHEUS_SUFFIXES:
        if metric_name.endswith(suffix):
            candidates.append(metric_name[: -len(suffix)])
    return any(c in metrics_code for c in candidates)


def test_alert_metrics_exist_in_code():
    """Every ``nexus_*`` metric in nexus_alerts.yml must be defined in code."""
    if not os.path.exists(ALERTS_PATH):
        pytest.skip(f"Alerts file not present: {ALERTS_PATH}")

    with open(ALERTS_PATH, encoding="utf-8") as f:
        alerts_text = f.read()

    referenced = _collect_referenced_metrics(alerts_text)
    assert referenced, "No nexus_ metrics found in alert rules"

    metrics_code = ""
    for path in METRICS_PATHS:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                metrics_code += f.read() + "\n"

    assert metrics_code, "No metrics source code found"

    undefined = sorted(
        m for m in referenced if not _metric_defined_in_code(m, metrics_code)
    )
    assert not undefined, (
        f"Alert rules reference undefined metrics: {undefined}. "
        f"Either define these metrics in nexus/observability/*.py "
        f"or fix the alert expressions."
    )


def test_no_deprecated_metric_names():
    """The old http_requests_total / etc. must not appear in alert rules."""
    if not os.path.exists(ALERTS_PATH):
        pytest.skip(f"Alerts file not present: {ALERTS_PATH}")
    with open(ALERTS_PATH, encoding="utf-8") as f:
        content = f.read()
    deprecated = [
        "http_requests_total",
        "http_request_duration_seconds",
        "requests_total",
    ]
    # Use word boundaries so e.g. "requests_total" doesn't match the suffix
    # of "nexus_api_requests_total" (which is the new, correct name).
    present = [
        d for d in deprecated
        if re.search(rf"\b{re.escape(d)}\b", content)
    ]
    assert not present, (
        f"Deprecated metric names still referenced in alert rules: {present}. "
        f"Use the ``nexus_*`` equivalents defined in nexus/observability/metrics.py."
    )


def test_alerts_yaml_loads_and_has_seven_rules():
    """The alerts file must parse and contain exactly 7 alert rules."""
    if not os.path.exists(ALERTS_PATH):
        pytest.skip(f"Alerts file not present: {ALERTS_PATH}")
    with open(ALERTS_PATH, encoding="utf-8") as f:
        alerts = yaml.safe_load(f)
    rules = []
    for group in alerts.get("groups", []):
        for rule in group.get("rules", []):
            if "alert" in rule:
                rules.append(rule["alert"])
    assert len(rules) == 7, (
        f"Expected 7 alert rules, found {len(rules)}: {rules}"
    )
