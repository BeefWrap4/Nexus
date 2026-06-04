import pytest
from nexus.billing.models import SubscriptionPlan, UsageRecord, BillingPeriod
from nexus.billing.plans import PLANS
from nexus.billing.meter import UsageMeter


class TestSubscriptionPlan:
    def test_free_plan(self):
        plan = PLANS["free"]
        assert plan.price_usd == 0.0
        assert plan.max_workflows == 10
        assert plan.max_llm_calls_per_day == 100

    def test_pro_plan(self):
        plan = PLANS["pro"]
        assert plan.price_usd == 49.0
        assert plan.max_agents == 20

    def test_enterprise_plan(self):
        plan = PLANS["enterprise"]
        assert plan.price_usd == 299.0
        assert "SSO" in plan.features


class TestUsageMeter:
    @pytest.fixture
    def meter(self):
        return UsageMeter()

    def test_default_plan_is_free(self, meter):
        plan = meter.get_plan("tenant1")
        assert plan.plan_id == "free"

    def test_set_plan(self, meter):
        meter.set_plan("tenant1", "pro")
        assert meter.get_plan("tenant1").plan_id == "pro"

    def test_record_and_get_usage(self, meter):
        meter.record_usage("tenant1", "llm_calls", value=5.0)
        meter.record_usage("tenant1", "llm_calls", value=3.0)
        usage = meter.get_usage("tenant1", "llm_calls")
        assert usage == 8.0

    def test_quota_ok(self, meter):
        ok, msg = meter.check_quota("tenant1", "llm_calls")
        assert ok is True

    def test_quota_exceeded(self, meter):
        meter.set_plan("tenant1", "free")
        meter.record_usage("tenant1", "llm_calls", value=200.0)  # free limit is 100
        ok, msg = meter.check_quota("tenant1", "llm_calls")
        assert ok is False
        assert "exceeded" in msg

    def test_unknown_plan_raises(self, meter):
        with pytest.raises(ValueError):
            meter.set_plan("tenant1", "nonexistent")

    def test_usage_report(self, meter):
        meter.set_plan("tenant1", "pro")
        meter.record_usage("tenant1", "llm_calls", value=42)
        report = meter.get_usage_report("tenant1")
        assert report["plan"] == "Professional"
        assert report["price"] == "$49.0/mo"

    def test_tenant_isolation(self, meter):
        meter.record_usage("tenant1", "llm_calls", value=10)
        meter.record_usage("tenant2", "llm_calls", value=20)
        assert meter.get_usage("tenant1", "llm_calls") == 10
        assert meter.get_usage("tenant2", "llm_calls") == 20
