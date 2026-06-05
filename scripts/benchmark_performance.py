#!/usr/bin/env python3
"""NEXUS 性能基准测试 — 验证生产负载能力."""
import time
import statistics
import concurrent.futures
import requests

API = "http://localhost:8765"
HEADERS = {
    "X-API-Key": "nexus_devkey_api_key_for_testing_and_docs",
    "Content-Type": "application/json",
}


def measure_latency(name: str, func, iterations: int = 50) -> dict:
    """测量操作延迟."""
    times = []
    errors = 0
    for _ in range(iterations):
        start = time.perf_counter()
        try:
            func()
        except Exception:
            errors += 1
        times.append(time.perf_counter() - start)

    times.sort()
    return {
        "name": name,
        "iterations": iterations,
        "errors": errors,
        "p50_ms": round(times[len(times)//2] * 1000, 1),
        "p95_ms": round(times[int(len(times)*0.95)] * 1000, 1),
        "p99_ms": round(times[int(len(times)*0.99)] * 1000, 1),
        "mean_ms": round(statistics.mean(times) * 1000, 1),
        "min_ms": round(min(times) * 1000, 1),
        "max_ms": round(max(times) * 1000, 1),
    }


def api_health():
    requests.get(f"{API}/health", timeout=5)


def api_workflows_list():
    requests.get(f"{API}/api/v1/workflows/", headers=HEADERS, timeout=10)


def api_agents_list():
    requests.get(f"{API}/api/v1/agents/", headers=HEADERS, timeout=10)


def api_tools_list():
    requests.get(f"{API}/api/v1/tools/", headers=HEADERS, timeout=10)


def api_metrics():
    requests.get(f"{API}/metrics", timeout=5)


def concurrent_test(name: str, func, concurrency: int = 20) -> dict:
    """并发测试."""
    start = time.perf_counter()
    errors = 0
    success = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(func) for _ in range(concurrency)]
        for f in concurrent.futures.as_completed(futures):
            try:
                f.result()
                success += 1
            except Exception:
                errors += 1

    elapsed = time.perf_counter() - start
    return {
        "name": name,
        "concurrency": concurrency,
        "elapsed_ms": round(elapsed * 1000, 1),
        "throughput_rps": round(concurrency / elapsed, 1),
        "success": success,
        "errors": errors,
    }


def workflow_create_flow():
    """创建工作流 → 删除（轻量级数据写入测试）."""
    resp = requests.post(
        f"{API}/api/v1/agents/",
        headers=HEADERS,
        json={
            "name": f"perf-test-{time.time_ns() % 10000}",
            "role": "Performance Tester",
            "goal": "Load test",
            "backstory": "Testing",
            "llm_settings": {"provider": "deepseek", "model": "deepseek-chat"},
        },
        timeout=10,
    )
    if resp.status_code in (200, 201):
        agent_id = resp.json().get("id")
        if agent_id:
            requests.delete(f"{API}/api/v1/agents/{agent_id}", headers=HEADERS, timeout=5)


if __name__ == "__main__":
    print("=" * 65)
    print("  NEXUS Performance Benchmark")
    print("=" * 65)
    print()

    # ── 1. API 延迟测试 ──────────────────────────────
    print("📊 API Latency (50 iterations each)")
    print("-" * 50)

    results = []
    for name, fn in [
        ("Health Check", api_health),
        ("Workflows List", api_workflows_list),
        ("Agents List", api_agents_list),
        ("Tools List", api_tools_list),
        ("Metrics (Prometheus)", api_metrics),
    ]:
        r = measure_latency(f"GET {name}", fn)
        results.append(r)
        status = "✅" if r["errors"] == 0 else f"⚠️ {r['errors']}err"
        print(f"  {status} {name:20s}: p50={r['p50_ms']:6.1f}ms  p95={r['p95_ms']:6.1f}ms  p99={r['p99_ms']:6.1f}ms")

    print()

    # ── 2. 并发测试 ──────────────────────────────────
    print("⚡ Concurrent Throughput")
    print("-" * 50)

    for name, fn, conc in [
        ("Health Check x50", api_health, 50),
        ("Workflows List x30", api_workflows_list, 30),
        ("Agents List x30", api_agents_list, 30),
    ]:
        r = concurrent_test(name, fn, conc)
        status = "✅" if r["errors"] == 0 else f"⚠️ {r['errors']}err"
        print(f"  {status} {name:25s}: {r['throughput_rps']:6.1f} req/s  ({r['concurrency']} in {r['elapsed_ms']:.0f}ms)")

    print()

    # ── 3. 数据库写入并发 ────────────────────────────
    print("💾 Database Write Concurrency")
    print("-" * 50)

    r = concurrent_test("Agent Create+Delete x10", workflow_create_flow, 10)
    status = "✅" if r["errors"] == 0 else f"⚠️ {r['errors']}err"
    print(f"  {status} Agent CRUD x10:          {r['throughput_rps']:6.1f} ops/s  ({r['success']} success, {r['errors']} errors)")

    print()

    # ── 4. 系统资源快照 ──────────────────────────────
    print("📈 System Status")
    print("-" * 50)

    try:
        r = measure_latency("Health", api_health, 3)
        import subprocess
        result = subprocess.run(
            ["docker", "stats", "--no-stream", "--format",
             "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}",
             "nexus-api", "nexus-worker", "nexus-postgres"],
            capture_output=True, text=True, timeout=5,
        )
        print(result.stdout)
    except Exception as e:
        print(f"  (docker stats unavailable: {e})")

    print()

    # ── 5. Summary ───────────────────────────────────
    print("=" * 65)
    print("  Benchmark Complete")
    print("=" * 65)

    health_r = [r for r in results if "Health" in r["name"]][0]
    wf_r = [r for r in results if "Workflow" in r["name"]][0]

    print(f"  Health p95:          {health_r['p95_ms']}ms")
    print(f"  Workflow List p95:   {wf_r['p95_ms']}ms")
    print(f"  All API errors:      {sum(r['errors'] for r in results)}")
    print(f"  Write test errors:   {r['errors'] if 'r' in dir() else 'N/A'}")

    if health_r["p95_ms"] < 50 and wf_r["p95_ms"] < 500:
        print("\n  🟢 NEXUS is production-ready!")
    elif health_r["p95_ms"] < 200 and wf_r["p95_ms"] < 2000:
        print("\n  🟡 NEXUS needs optimization before production.")
    else:
        print("\n  🔴 NEXUS performance is below acceptable thresholds.")
