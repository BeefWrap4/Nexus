import pytest
import pytest_asyncio
from nexus.billing.meter import DbUsageMeter


class TestDbUsageMeter:
    @pytest_asyncio.fixture
    async def meter(self, db_session):
        return DbUsageMeter()

    @pytest.mark.asyncio
    async def test_has_plan_defaults(self, meter):
        """数据库计量器继承基础行为."""
        plan = meter.get_plan("tenant99")
        assert plan.plan_id == "free"

    @pytest.mark.asyncio
    async def test_set_plan(self, meter):
        meter.set_plan("tenant99", "pro")
        assert meter.get_plan("tenant99").plan_id == "pro"

    @pytest.mark.asyncio
    async def test_record_usage_in_memory(self, meter):
        """record_usage 写入内存缓存."""
        await meter.record_usage("t1", "llm_calls", value=5.0)
        await meter.record_usage("t1", "llm_calls", value=3.0)
        usage = await meter.get_usage("t1", "llm_calls")
        assert usage == 8.0

    @pytest.mark.asyncio
    async def test_quota_enforcement(self, meter):
        """超限检测."""
        meter.set_plan("t1", "free")
        await meter.record_usage("t1", "llm_calls", value=150.0)
        ok, msg = await meter.check_quota("t1", "llm_calls")
        assert ok is False
        assert "exceeded" in msg

    @pytest.mark.asyncio
    async def test_usage_report(self, meter):
        meter.set_plan("t1", "pro")
        report = await meter.get_usage_report("t1")
        assert report["plan"] == "Professional"
        assert report["price"] == "$49.0/mo"
        assert "limits" in report

    @pytest.mark.asyncio
    async def test_tenant_isolation(self, meter):
        await meter.record_usage("a", "tokens", value=100)
        await meter.record_usage("b", "tokens", value=200)
        usage_a = await meter.get_usage("a", "tokens")
        usage_b = await meter.get_usage("b", "tokens")
        assert usage_a == 100
        assert usage_b == 200
