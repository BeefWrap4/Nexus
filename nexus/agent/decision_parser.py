"""决策解析器.

基于WAT agent/decision_parser.py 复用升级:
- 从LLM原始输出中提取结构化AgentDecision
- 支持JSON解析失败时的正则提取Fallback
- 扩展支持Tool Call解析
"""

import json
import re
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class AgentDecision:
    """Agent决策."""

    reasoning: str = ""
    action: str = "final_answer"  # final_answer / tool_call / think
    content: str = ""
    tool_name: str = ""
    tool_params: dict[str, Any] = None
    confidence: float = 0.0


class DecisionParser:
    """决策解析器.

    对应WAT agent/decision_parser.py。
    """

    def parse(self, response: dict[str, Any]) -> AgentDecision:
        """解析LLM响应为结构化决策.

        对应WAT BaseAgent._parse_decision()。
        """
        try:
            # 尝试标准OpenAI格式解析
            choice = response.get("choices", [{}])[0]
            message = choice.get("message", {})

            # 检查Tool Calls
            tool_calls = message.get("tool_calls")
            if tool_calls:
                tool = tool_calls[0]
                return AgentDecision(
                    reasoning="Using tool",
                    action="tool_call",
                    tool_name=tool.get("function", {}).get("name", ""),
                    tool_params=json.loads(
                        tool.get("function", {}).get("arguments", "{}")
                    ),
                )

            content = message.get("content", "")
            return self._parse_content(content)

        except Exception:
            # Fallback: 尝试从content直接解析
            content = str(response)
            return self._parse_content(content)

    def _parse_content(self, content: str) -> AgentDecision:
        """从文本内容解析决策."""
        # 尝试JSON解析
        try:
            data = json.loads(content)
            return AgentDecision(
                reasoning=data.get("reasoning", ""),
                action=data.get("action", "final_answer"),
                content=data.get("content", ""),
                tool_name=data.get("tool_name", ""),
                tool_params=data.get("tool_params"),
                confidence=data.get("confidence", 0.0),
            )
        except json.JSONDecodeError:
            pass

        # Fallback: 正则提取
        action_match = re.search(r'action["\']?\s*[:=]\s*["\']?(\w+)', content, re.I)
        action = action_match.group(1).lower() if action_match else "final_answer"

        reasoning_match = re.search(r'reasoning["\']?\s*[:=]\s*["\']?([^"\']+)', content, re.I)
        reasoning = reasoning_match.group(1) if reasoning_match else ""

        # 清理CoT泄露（复用WAT设计）
        content = self._clean_cot_leakage(content)

        return AgentDecision(
            reasoning=reasoning,
            action=action,
            content=content,
        )

    def _clean_cot_leakage(self, content: str) -> str:
        """清理CoT推理泄露（复用WAT BaseAgent._clean_cot_leakage）.

        防止模型将思考过程混入输出。
        """
        # 移除常见的思考标记
        patterns = [
            r"<think>.*?</think>",
            r"<reasoning>.*?</reasoning>",
            r"Thinking:.*?\n",
            r"Let me think.*?\n",
        ]
        for pattern in patterns:
            content = re.sub(pattern, "", content, flags=re.DOTALL | re.IGNORECASE)
        return content.strip()
