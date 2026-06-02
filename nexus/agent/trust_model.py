"""信任模型.

基于WAT agent/trust_model.py 泛化:
- 从狼人杀专用信任评估泛化为通用信任评估
- 保留贝叶斯信念更新框架
- 保留17种证据类型（部分泛化）
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TrustEvaluation:
    """信任评估结果."""

    target_id: str
    trust_score: float  # -1.0 (完全不信任) 到 1.0 (完全信任)
    belief: float  # 0.0 到 1.0
    evidence: list[str] = field(default_factory=list)
    confidence: float = 0.5


class TrustModel:
    """信任模型.

    对应WAT agent/trust_model.py。
    贝叶斯信念系统，支持多维度证据更新。
    """

    def __init__(self):
        # 信任度: target_id -> [-1.0, 1.0]
        self.trust_map: dict[str, float] = {}
        # 信念: target_id -> [0.0, 1.0]
        self.belief_model: dict[str, float] = {}

    def update(
        self,
        target_id: str,
        evidence_type: str,
        strength: float = 1.0,
        context: Optional[dict] = None,
    ) -> TrustEvaluation:
        """基于证据更新信任度.

        对应WAT TrustModel._bayesian_update()。
        """
        # 获取当前信任度
        current_trust = self.trust_map.get(target_id, 0.0)
        current_belief = self.belief_model.get(target_id, 0.5)

        # 根据证据类型计算似然比
        likelihood = self._get_likelihood(evidence_type, strength)

        # 贝叶斯更新
        new_belief = self._bayesian_update(current_belief, likelihood)
        new_belief = max(0.05, min(0.95, new_belief))  # 边界保护

        # 信任度更新（启发式）
        trust_delta = strength * 0.1 * (1 if likelihood > 1.0 else -1)
        new_trust = max(-1.0, min(1.0, current_trust + trust_delta))

        # 保存
        self.belief_model[target_id] = new_belief
        self.trust_map[target_id] = new_trust

        return TrustEvaluation(
            target_id=target_id,
            trust_score=new_trust,
            belief=new_belief,
            evidence=[evidence_type],
            confidence=min(1.0, abs(new_trust) + 0.5),
        )

    def _get_likelihood(self, evidence_type: str, strength: float) -> float:
        """获取证据类型的似然比.

        对应WAT TrustModel的17种证据类型。
        泛化为通用业务场景。
        """
        likelihood_map = {
            # 正面证据
            "successful_collaboration": 2.0,
            "accurate_prediction": 1.8,
            "timely_delivery": 1.5,
            "high_quality_output": 1.6,
            "positive_feedback": 1.4,
            "reliable_execution": 1.5,

            # 负面证据
            "failed_task": 0.3,
            "inaccurate_output": 0.4,
            "missed_deadline": 0.5,
            "low_quality_output": 0.4,
            "negative_feedback": 0.5,
            "unreliable_behavior": 0.4,

            # 中性/弱证据
            "neutral_interaction": 1.0,
            "limited_data": 0.9,
            "inconsistent_behavior": 0.7,
        }

        base = likelihood_map.get(evidence_type, 1.0)
        return base ** strength

    def _bayesian_update(self, prior: float, likelihood: float) -> float:
        """贝叶斯更新.

        P(H|E) = P(E|H) * P(H) / [P(E|H)*P(H) + P(E|~H)*P(~H)]
        """
        if likelihood >= 1.0:
            # 正面证据
            posterior = (likelihood * prior) / (
                likelihood * prior + (1 - prior)
            )
        else:
            # 负面证据
            posterior = (likelihood * prior) / (
                likelihood * prior + (1 - likelihood) * (1 - prior)
            )
        return posterior

    def get_trust(self, target_id: str) -> float:
        """获取信任度."""
        return self.trust_map.get(target_id, 0.0)

    def get_belief(self, target_id: str) -> float:
        """获取信念值."""
        return self.belief_model.get(target_id, 0.5)
