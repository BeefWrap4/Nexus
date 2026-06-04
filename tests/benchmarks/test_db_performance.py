"""数据库性能基准测试.

测试数据库批量插入、复杂查询、Checkpoint读写等关键操作的性能。
"""

import asyncio
import time
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select, func

from nexus.observability.slo import SLO
from nexus.db.database import AsyncSessionLocal, init_db
from nexus.models.llm_trace import LLMCallTrace
from nexus.models.workflow import Workflow, WorkflowRun, NodeRun, CheckpointRecord


@pytest.fixture(scope="module")
def event_loop():
    """创建事件循环供异步测试使用."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
async def setup_database():
    """初始化数据库."""
    await init_db()
    yield
    # 清理测试数据（可选）


async def measure_query_performance(query_func, iterations: int = 100):
    """测量查询性能的辅助函数.

    Returns:
        (平均延迟ms, P95延迟ms, P99延迟ms)
    """
    latencies = []

    for _ in range(iterations):
        start_time = time.time()
        await query_func()
        duration_ms = (time.time() - start_time) * 1000
        latencies.append(duration_ms)

    latencies.sort()
    avg_latency = sum(latencies) / len(latencies)
    p95_idx = int(len(latencies) * 0.95)
    p99_idx = int(len(latencies) * 0.99)

    p95 = latencies[min(p95_idx, len(latencies) - 1)]
    p99 = latencies[min(p99_idx, len(latencies) - 1)]

    return avg_latency, p95, p99


@pytest.mark.benchmark
@pytest.mark.asyncio
async def test_db_batch_insert_llm_traces():
    """测试LLM Trace批量插入性能.

    模拟高频LLM调用场景下的批量写入性能。
    """
    batch_size = 100
    num_batches = 10

    async with AsyncSessionLocal() as session:
        start_time = time.time()

        for batch_idx in range(num_batches):
            traces = []
            for i in range(batch_size):
                trace = LLMCallTrace(
                    tenant_id=str(uuid.uuid4()),
                    run_id=str(uuid.uuid4()),
                    node_id=f"node_{i}",
                    agent_id=f"agent_{batch_idx}",
                    model="gpt-4o",
                    provider="openai",
                    system_prompt=f"Test system prompt {i}",
                    user_prompt=f"Test user prompt {i}",
                    response_content=f"Test response {i}",
                    prompt_tokens=100 + i,
                    completion_tokens=50 + i,
                    total_tokens=150 + i * 2,
                    latency_ms=500 + i * 10,
                    cache_hit=i % 10 == 0,
                )
                traces.append(trace)

            session.add_all(traces)
            await session.commit()

        total_duration_ms = (time.time() - start_time) * 1000
        total_records = batch_size * num_batches
        avg_insert_time = total_duration_ms / total_records

        print(f"✓ LLM Trace批量插入测试:")
        print(f"  - 总记录数: {total_records}")
        print(f"  - 批次大小: {batch_size}")
        print(f"  - 总耗时: {total_duration_ms:.2f}ms")
        print(f"  - 平均单条插入时间: {avg_insert_time:.2f}ms")

        # 验证性能：平均插入时间应该合理
        assert avg_insert_time < 10, f"插入性能过差: {avg_insert_time:.2f}ms/record"


@pytest.mark.benchmark
@pytest.mark.asyncio
async def test_db_complex_query_workflow_runs():
    """测试工作流运行记录的复杂查询性能.

    包括多表JOIN、聚合、排序等操作。
    """
    # 先插入一些测试数据
    async with AsyncSessionLocal() as session:
        for i in range(50):
            workflow = Workflow(
                id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                created_by=uuid.uuid4(),
                name=f"test_workflow_{i}",
                description=f"Test workflow {i}",
                status="active",
                config={"nodes": [], "edges": []},
            )
            session.add(workflow)
        await session.commit()

        for i in range(200):
            run = WorkflowRun(
                id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                workflow_id=None,  # 简化测试
                version=1,
                status="completed" if i % 5 != 0 else "failed",
                trigger_type="api",
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
            )
            session.add(run)
        await session.commit()

    # 执行复杂查询
    async def complex_query():
        async with AsyncSessionLocal() as session:
            # 查询：按状态统计工作流运行数量，按租户分组
            stmt = (
                select(
                    WorkflowRun.tenant_id,
                    WorkflowRun.status,
                    func.count(WorkflowRun.id).label("count"),
                )
                .group_by(WorkflowRun.tenant_id, WorkflowRun.status)
                .order_by(func.count(WorkflowRun.id).desc())
            )
            result = await session.execute(stmt)
            rows = result.all()
            return rows

    avg_latency, p95, p99 = await measure_query_performance(complex_query, iterations=50)

    print(f"✓ 复杂查询性能测试:")
    print(f"  - 平均延迟: {avg_latency:.2f}ms (目标: <{SLO.DB_QUERY_P50_MS}ms)")
    print(f"  - P95延迟: {p95:.2f}ms (目标: <{SLO.DB_QUERY_P95_MS}ms)")
    print(f"  - P99延迟: {p99:.2f}ms (目标: <{SLO.DB_QUERY_P99_MS}ms)")

    assert avg_latency < SLO.DB_QUERY_P50_MS * 5, f"平均查询延迟过高: {avg_latency:.2f}ms"
    assert p95 < SLO.DB_QUERY_P95_MS * 3, f"P95查询延迟过高: {p95:.2f}ms"


@pytest.mark.benchmark
@pytest.mark.asyncio
async def test_db_checkpoint_read_write():
    """测试Checkpoint读写性能.

    Checkpoint是工作流状态恢复的关键，需要高性能。
    """
    num_checkpoints = 100

    # 批量写入Checkpoints
    async with AsyncSessionLocal() as session:
        start_time = time.time()

        checkpoints = []
        for i in range(num_checkpoints):
            checkpoint = CheckpointRecord(
                id=f"checkpoint_{i}",
                run_id=uuid.uuid4(),
                node_id=f"node_{i % 10}",
                state_data={"step": i, "status": "running"},
            )
            checkpoints.append(checkpoint)

        session.add_all(checkpoints)
        await session.commit()

        write_duration_ms = (time.time() - start_time) * 1000
        avg_write_time = write_duration_ms / num_checkpoints

    # 批量读取Checkpoints
    async def read_checkpoints():
        async with AsyncSessionLocal() as session:
            stmt = select(CheckpointRecord).where(
                CheckpointRecord.id.in_([f"checkpoint_{i}" for i in range(10)])
            )
            result = await session.execute(stmt)
            return result.scalars().all()

    read_avg, read_p95, read_p99 = await measure_query_performance(
        read_checkpoints, iterations=50
    )

    print(f"✓ Checkpoint读写性能测试:")
    print(f"  - 批量写入({num_checkpoints}条): {write_duration_ms:.2f}ms")
    print(f"  - 平均写入时间: {avg_write_time:.2f}ms/record")
    print(f"  - 读取平均延迟: {read_avg:.2f}ms")
    print(f"  - 读取P95延迟: {read_p95:.2f}ms")
    print(f"  - 读取P99延迟: {read_p99:.2f}ms")

    assert avg_write_time < 5, f"Checkpoint写入性能过差: {avg_write_time:.2f}ms"
    assert read_avg < SLO.DB_QUERY_P50_MS * 3, f"Checkpoint读取延迟过高: {read_avg:.2f}ms"


@pytest.mark.benchmark
@pytest.mark.asyncio
async def test_db_concurrent_operations():
    """测试数据库并发操作性能.

    验证在高并发场景下数据库的性能表现。
    """
    num_concurrent = 20

    async def insert_and_query(idx: int):
        async with AsyncSessionLocal() as session:
            # 插入
            trace = LLMCallTrace(
                tenant_id=str(uuid.uuid4()),
                run_id=str(uuid.uuid4()),
                model="gpt-4o",
                provider="openai",
                user_prompt=f"Concurrent test {idx}",
                response_content=f"Response {idx}",
                total_tokens=100,
                latency_ms=500,
            )
            session.add(trace)
            await session.commit()

            # 查询
            stmt = select(LLMCallTrace).where(
                LLMCallTrace.response_content == f"Response {idx}"
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    start_time = time.time()
    tasks = [insert_and_query(i) for i in range(num_concurrent)]
    results = await asyncio.gather(*tasks)
    total_duration_ms = (time.time() - start_time) * 1000

    success_count = sum(1 for r in results if r is not None)
    avg_operation_time = total_duration_ms / num_concurrent

    print(f"✓ 数据库并发操作测试:")
    print(f"  - 并发数: {num_concurrent}")
    print(f"  - 成功数: {success_count}/{num_concurrent}")
    print(f"  - 总耗时: {total_duration_ms:.2f}ms")
    print(f"  - 平均操作时间: {avg_operation_time:.2f}ms")

    assert success_count == num_concurrent, "存在并发操作失败"
    assert avg_operation_time < 50, f"并发操作性能过差: {avg_operation_time:.2f}ms"


@pytest.mark.benchmark
@pytest.mark.asyncio
async def test_db_index_efficiency():
    """测试数据库索引效率.

    验证索引是否正确创建并有效提升查询性能。
    """
    # 插入大量数据
    num_records = 1000

    async with AsyncSessionLocal() as session:
        traces = []
        for i in range(num_records):
            trace = LLMCallTrace(
                tenant_id="00000000-0000-0000-0000-000000000001",  # 固定tenant_id用于测试索引
                run_id=str(uuid.uuid4()),
                model="gpt-4o" if i % 2 == 0 else "gpt-3.5-turbo",
                provider="openai",
                user_prompt=f"Index test {i}",
                response_content=f"Response {i}",
                total_tokens=100 + i,
                latency_ms=500 + i,
                cache_hit=i % 10 == 0,
            )
            traces.append(trace)

        session.add_all(traces)
        await session.commit()

    # 测试带索引的查询（按tenant_id和model过滤）
    async def indexed_query():
        async with AsyncSessionLocal() as session:
            stmt = (
                select(LLMCallTrace)
                .where(
                    LLMCallTrace.tenant_id == "00000000-0000-0000-0000-000000000001",
                    LLMCallTrace.model == "gpt-4o",
                )
                .limit(10)
            )
            result = await session.execute(stmt)
            return result.scalars().all()

    avg_latency, p95, p99 = await measure_query_performance(indexed_query, iterations=30)

    print(f"✓ 索引效率测试:")
    print(f"  - 数据量: {num_records}条")
    print(f"  - 平均查询延迟: {avg_latency:.2f}ms")
    print(f"  - P95延迟: {p95:.2f}ms")
    print(f"  - P99延迟: {p99:.2f}ms")

    # 有索引的查询应该非常快
    assert avg_latency < SLO.DB_QUERY_P95_MS, f"索引查询延迟过高: {avg_latency:.2f}ms"


@pytest.mark.benchmark
@pytest.mark.asyncio
async def test_db_transaction_overhead():
    """测试事务开销.

    验证事务提交和回滚的性能影响。
    """
    num_transactions = 50

    # 测试正常提交
    start_time = time.time()
    for i in range(num_transactions):
        async with AsyncSessionLocal() as session:
            trace = LLMCallTrace(
                tenant_id=str(uuid.uuid4()),
                model="gpt-4o",
                user_prompt=f"Transaction test {i}",
                response_content=f"Response {i}",
            )
            session.add(trace)
            await session.commit()
    commit_duration_ms = (time.time() - start_time) * 1000

    # 测试回滚
    start_time = time.time()
    for i in range(num_transactions):
        try:
            async with AsyncSessionLocal() as session:
                trace = LLMCallTrace(
                    tenant_id=str(uuid.uuid4()),
                    model="gpt-4o",
                    user_prompt=f"Rollback test {i}",
                    response_content=f"Response {i}",
                )
                session.add(trace)
                raise Exception("Intentional error for rollback test")
        except Exception:
            pass  # 预期会回滚
    rollback_duration_ms = (time.time() - start_time) * 1000

    avg_commit_time = commit_duration_ms / num_transactions
    avg_rollback_time = rollback_duration_ms / num_transactions

    print(f"✓ 事务开销测试:")
    print(f"  - 平均提交时间: {avg_commit_time:.2f}ms")
    print(f"  - 平均回滚时间: {avg_rollback_time:.2f}ms")

    assert avg_commit_time < 10, f"事务提交开销过大: {avg_commit_time:.2f}ms"
    assert avg_rollback_time < 10, f"事务回滚开销过大: {avg_rollback_time:.2f}ms"
