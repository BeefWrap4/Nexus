"""API吞吐量基准测试.

使用httpx进行并发HTTP请求测试，验证API性能和吞吐量是否满足SLO要求。
"""

import asyncio
import time
from typing import List, Tuple

import httpx
import pytest

from nexus.observability.slo import SLO


# API基础URL（测试时使用）
BASE_URL = "http://localhost:8000"


async def make_api_request(
    client: httpx.AsyncClient, method: str, endpoint: str, **kwargs
) -> Tuple[float, int, dict]:
    """发起单个API请求并返回性能数据.

    Returns:
        (延迟毫秒, 状态码, 响应数据)
    """
    start_time = time.time()
    try:
        response = await client.request(method, f"{BASE_URL}{endpoint}", **kwargs)
        duration_ms = (time.time() - start_time) * 1000
        return duration_ms, response.status_code, response.json()
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        return duration_ms, 0, {"error": str(e)}


@pytest.mark.benchmark
@pytest.mark.asyncio
async def test_api_latency_single_request():
    """测试单API请求延迟.

    验证基本API调用的P50、P95、P99延迟是否满足SLO。
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        # 预热请求
        await client.get(f"{BASE_URL}/health")

        # 执行多次请求以计算百分位数
        num_requests = 100
        latencies = []

        for _ in range(num_requests):
            duration_ms, status_code, _ = await make_api_request(
                client, "GET", "/health"
            )
            if status_code == 200:
                latencies.append(duration_ms)

        assert len(latencies) > 0, "没有成功的请求"

        # 计算百分位数
        latencies.sort()
        p50_idx = int(len(latencies) * 0.50)
        p95_idx = int(len(latencies) * 0.95)
        p99_idx = int(len(latencies) * 0.99)

        p50 = latencies[p50_idx]
        p95 = latencies[min(p95_idx, len(latencies) - 1)]
        p99 = latencies[min(p99_idx, len(latencies) - 1)]

        print(f"✓ API延迟测试结果:")
        print(f"  - P50: {p50:.2f}ms (目标: <{SLO.API_P50_LATENCY_MS}ms)")
        print(f"  - P95: {p95:.2f}ms (目标: <{SLO.API_P95_LATENCY_MS}ms)")
        print(f"  - P99: {p99:.2f}ms (目标: <{SLO.API_P99_LATENCY_MS}ms)")

        # 验证SLO
        assert p50 < SLO.API_P50_LATENCY_MS, f"P50延迟超标: {p50:.2f}ms"
        assert p95 < SLO.API_P95_LATENCY_MS, f"P95延迟超标: {p95:.2f}ms"
        assert p99 < SLO.API_P99_LATENCY_MS, f"P99延迟超标: {p99:.2f}ms"


@pytest.mark.benchmark
@pytest.mark.asyncio
async def test_api_throughput_concurrent():
    """测试API并发吞吐量.

    验证系统能否处理高并发请求并保持合理的延迟。
    """
    num_concurrent = 50
    num_requests = 200

    async with httpx.AsyncClient(timeout=10.0) as client:
        # 预热
        await client.get(f"{BASE_URL}/health")

        # 并发执行请求
        async def batch_request(batch_size: int):
            tasks = [
                make_api_request(client, "GET", "/health")
                for _ in range(batch_size)
            ]
            return await asyncio.gather(*tasks)

        all_latencies = []
        success_count = 0
        error_count = 0

        start_time = time.time()

        # 分批执行
        for i in range(0, num_requests, num_concurrent):
            batch_size = min(num_concurrent, num_requests - i)
            results = await batch_request(batch_size)

            for duration_ms, status_code, _ in results:
                if status_code == 200:
                    all_latencies.append(duration_ms)
                    success_count += 1
                else:
                    error_count += 1

        total_duration_s = time.time() - start_time

        # 计算吞吐量
        throughput_rps = success_count / total_duration_s if total_duration_s > 0 else 0

        # 计算延迟统计
        if all_latencies:
            all_latencies.sort()
            avg_latency = sum(all_latencies) / len(all_latencies)
            p95_idx = int(len(all_latencies) * 0.95)
            p95_latency = all_latencies[min(p95_idx, len(all_latencies) - 1)]
        else:
            avg_latency = 0
            p95_latency = 0

        print(f"✓ API吞吐量测试结果:")
        print(f"  - 总请求数: {num_requests}")
        print(f"  - 成功数: {success_count}")
        print(f"  - 失败数: {error_count}")
        print(f"  - 总耗时: {total_duration_s:.2f}s")
        print(f"  - 吞吐量: {throughput_rps:.2f} req/s (目标: >{SLO.API_THROUGHPUT_RPS} req/s)")
        print(f"  - 平均延迟: {avg_latency:.2f}ms")
        print(f"  - P95延迟: {p95_latency:.2f}ms")

        # 验证SLO
        assert success_count > num_requests * 0.95, "成功率低于95%"
        assert throughput_rps >= SLO.API_THROUGHPUT_RPS * 0.5, (
            f"吞吐量过低: {throughput_rps:.2f} req/s"
        )
        assert p95_latency < SLO.API_P95_LATENCY_MS * 2, (
            f"高负载下P95延迟过高: {p95_latency:.2f}ms"
        )


@pytest.mark.benchmark
@pytest.mark.asyncio
async def test_api_error_rate():
    """测试API错误率.

    验证在正常负载下的错误率是否在可接受范围内。
    """
    num_requests = 100

    async with httpx.AsyncClient(timeout=10.0) as client:
        error_count = 0
        success_count = 0

        for _ in range(num_requests):
            _, status_code, _ = await make_api_request(client, "GET", "/health")
            if status_code == 200:
                success_count += 1
            else:
                error_count += 1

        error_rate = error_count / num_requests if num_requests > 0 else 0

        print(f"✓ API错误率测试:")
        print(f"  - 总请求: {num_requests}")
        print(f"  - 成功: {success_count}")
        print(f"  - 失败: {error_count}")
        print(f"  - 错误率: {error_rate * 100:.2f}% (阈值: <{SLO.ERROR_RATE_THRESHOLD * 100}%)")

        assert error_rate <= SLO.ERROR_RATE_THRESHOLD, (
            f"错误率超标: {error_rate * 100:.2f}%"
        )


@pytest.mark.skip(reason="需要真实的工作流API端点")
@pytest.mark.benchmark
@pytest.mark.asyncio
async def test_workflow_api_performance():
    """测试工作流相关API的性能.

    包括：创建工作流、启动工作流、查询状态等。
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        # 测试创建工作流API
        workflow_def = {
            "name": "benchmark_workflow",
            "nodes": [
                {"id": "start", "type": "start"},
                {"id": "end", "type": "end"},
            ],
            "edges": [{"source": "start", "target": "end"}],
        }

        durations = []
        for _ in range(10):
            start_time = time.time()
            response = await client.post(
                f"{BASE_URL}/api/v1/workflows",
                json=workflow_def,
            )
            duration_ms = (time.time() - start_time) * 1000
            if response.status_code == 201:
                durations.append(duration_ms)

        if durations:
            avg_duration = sum(durations) / len(durations)
            print(f"✓ 创建工作流API平均延迟: {avg_duration:.2f}ms")
            assert avg_duration < 500, f"创建工作流API延迟过高: {avg_duration:.2f}ms"


@pytest.mark.benchmark
@pytest.mark.asyncio
async def test_api_stability_under_load():
    """测试API在持续负载下的稳定性.

    模拟长时间运行，验证是否有内存泄漏或性能退化。
    """
    duration_seconds = 10  # 测试持续时间
    requests_per_second = 10  # 每秒请求数

    async with httpx.AsyncClient(timeout=10.0) as client:
        latencies_over_time = []
        errors_over_time = []

        start_time = time.time()
        request_count = 0

        while time.time() - start_time < duration_seconds:
            batch_start = time.time()

            # 在一秒内发送指定数量的请求
            tasks = [
                make_api_request(client, "GET", "/health")
                for _ in range(requests_per_second)
            ]
            results = await asyncio.gather(*tasks)

            batch_duration = time.time() - batch_start

            for duration_ms, status_code, _ in results:
                latencies_over_time.append((request_count, duration_ms))
                if status_code != 200:
                    errors_over_time.append(request_count)

            request_count += requests_per_second

            # 控制节奏
            sleep_time = max(0, 1.0 - batch_duration)
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)

        # 分析结果
        total_requests = len(latencies_over_time)
        total_errors = len(errors_over_time)
        error_rate = total_errors / total_requests if total_requests > 0 else 0

        # 检查是否有性能退化（比较前半段和后半段的平均延迟）
        mid_point = total_requests // 2
        first_half_avg = sum(l for _, l in latencies_over_time[:mid_point]) / mid_point
        second_half_avg = sum(
            l for _, l in latencies_over_time[mid_point:]
        ) / (total_requests - mid_point)

        degradation_ratio = second_half_avg / first_half_avg if first_half_avg > 0 else 1

        print(f"✓ API稳定性测试结果:")
        print(f"  - 总请求数: {total_requests}")
        print(f"  - 错误数: {total_errors}")
        print(f"  - 错误率: {error_rate * 100:.2f}%")
        print(f"  - 前半段平均延迟: {first_half_avg:.2f}ms")
        print(f"  - 后半段平均延迟: {second_half_avg:.2f}ms")
        print(f"  - 性能退化比: {degradation_ratio:.2f}x")

        assert error_rate <= SLO.ERROR_RATE_THRESHOLD, (
            f"长期负载下错误率超标: {error_rate * 100:.2f}%"
        )
        assert degradation_ratio < 1.5, (
            f"性能退化明显: {degradation_ratio:.2f}x"
        )
