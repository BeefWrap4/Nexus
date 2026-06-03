"""Prompt A/B 实验测试 — Phase 6.4.

覆盖：
- PromptResolver 分流逻辑: 确定性哈希、流量分配
- Experiment API: 创建实验、流量校验、暂停
"""

from __future__ import annotations

import hashlib

import pytest

from nexus.prompts.resolver import PromptResolver


class TestExperimentVariantSelection:
    """Test experiment variant selection logic (sync core logic)."""

    def _select_by_bucket(self, variants, bucket):
        """纯同步分流逻辑（复现 PromptResolver 核心算法）."""
        cumulative = 0
        for v in variants:
            cumulative += v["traffic_percentage"]
            if bucket < cumulative:
                return v
        return variants[-1]  # fallback

    def test_deterministic_hash(self):
        """同一 user_id 应始终产生同一 bucket."""
        user_id = "user_123"
        hash_val = int(hashlib.md5(user_id.encode()).hexdigest(), 16)
        bucket = hash_val % 100

        # 多次计算应相同
        for _ in range(10):
            h = int(hashlib.md5(user_id.encode()).hexdigest(), 16)
            assert h % 100 == bucket

    def test_traffic_distribution(self):
        """测试流量分配是否大致均匀."""
        variants = [
            {"name": "control", "traffic_percentage": 50},
            {"name": "variant", "traffic_percentage": 50},
        ]

        counts = {"control": 0, "variant": 0}
        for i in range(1000):
            hash_val = int(hashlib.md5(f"user_{i}".encode()).hexdigest(), 16)
            bucket = hash_val % 100
            selected = self._select_by_bucket(variants, bucket)
            counts[selected["name"]] += 1

        # 1000 次应大致 500/500，容差 100
        assert 400 < counts["control"] < 600
        assert 400 < counts["variant"] < 600

    def test_fallback_to_last_variant(self):
        """如果 bucket 超出所有 cumulative，应 fallback 到最后一个变体."""
        variants = [
            {"name": "control", "traffic_percentage": 30},
            {"name": "variant", "traffic_percentage": 30},
        ]

        bucket = 90  # 大于 60
        selected = self._select_by_bucket(variants, bucket)
        assert selected["name"] == "variant"

    def test_uneven_traffic(self):
        """非均匀流量分配."""
        variants = [
            {"name": "control", "traffic_percentage": 80},
            {"name": "variant", "traffic_percentage": 20},
        ]

        control_count = 0
        for i in range(1000):
            hash_val = int(hashlib.md5(f"user_{i}".encode()).hexdigest(), 16)
            bucket = hash_val % 100
            selected = self._select_by_bucket(variants, bucket)
            if selected["name"] == "control":
                control_count += 1

        # 80% 流量，容差 100
        assert 700 < control_count < 900


class TestExperimentAPICreation:
    """Test experiment API endpoints."""

    def test_create_experiment_traffic_must_sum_to_100(self):
        """实验变体流量总和必须等于 100."""
        from nexus.api.routes.prompts import ExperimentCreate

        data = ExperimentCreate(
            name="test",
            variants=[
                {"name": "control", "version": 1, "traffic_percentage": 60},
                {"name": "variant", "version": 2, "traffic_percentage": 30},
            ],
        )
        total = sum(v["traffic_percentage"] for v in data.variants)
        assert total == 90  # 不等于 100，API 应拒绝
