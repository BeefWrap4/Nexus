"""PII检测与脱敏.

借鉴Portkey Guardrails设计。

集成路径:
- nexus.security.audit_middleware: 记录审计日志
- nexus.agent.llm_client.LLMClient: 对 LLM 输入/输出进行脱敏
- 由 settings.PII_ENABLED 控制总开关（默认 True）
"""

import re
from dataclasses import dataclass
from typing import Any, List, Union


@dataclass
class PIIFinding:
    """PII发现结果."""

    type: str
    start: int
    end: int
    value: str


class PIIGuard:
    """PII检测与脱敏.

    检测并脱敏个人身份信息（SSN、邮箱、手机号、信用卡、身份证、银行卡、地址等）。
    sanitize() 接受字符串、字典、列表（递归处理嵌套结构），便于直接套用到
    LLM messages、prompt 模板、HTTP 请求体等多种数据结构。
    """

    PII_PATTERNS = {
        "email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
        "phone": r"\b(?:\+?86)?1[3-9]\d{9}\b|\b\d{3}[-.]?\d{3}[-.]?\d{4}\b",
        "ssn": r"\b\d{3}-\d{2}-\d{4}\b",
        "credit_card": r"\b(?:\d{4}[- ]?){3}\d{4}\b",
        "id_card": r"\b\d{17}[\dXx]|\d{15}\b",  # 中国身份证
        "bank_card": r"\b(?:\d{4}[- ]?){3,4}\d{3,4}\b",
        "address": r"\b(?:省|市|区|县|街道|路|号|室|栋|单元)\b",
    }

    def sanitize(self, content: Union[str, dict, list, Any]) -> Any:
        """脱敏处理.

        支持三种输入类型（递归处理嵌套结构）:
        - str:  对字符串本身做 PII 替换
        - dict: 对每个 value 递归 sanitize（key 不变）
        - list: 对每个元素递归 sanitize
        - 其他: 原样返回

        将所有 PII 替换为 [TYPE_REDACTED]（如 [SSN_REDACTED]）。
        """
        if isinstance(content, dict):
            return {k: self.sanitize(v) for k, v in content.items()}
        if isinstance(content, list):
            return [self.sanitize(item) for item in content]
        if isinstance(content, str):
            if not content:
                return content
            sanitized = content
            for pii_type, pattern in self.PII_PATTERNS.items():
                sanitized = re.sub(
                    pattern,
                    f"[{pii_type.upper()}_REDACTED]",
                    sanitized,
                    flags=re.IGNORECASE,
                )
            return sanitized
        return content

    def detect(self, text: str) -> List[PIIFinding]:
        """检测PII.

        返回所有发现的PII位置。
        """
        if not text:
            return []

        findings = []
        for pii_type, pattern in self.PII_PATTERNS.items():
            for match in re.finditer(pattern, text, re.IGNORECASE):
                findings.append(
                    PIIFinding(
                        type=pii_type,
                        start=match.start(),
                        end=match.end(),
                        value=match.group(),
                    )
                )
        return findings

    def has_pii(self, text: str) -> bool:
        """检查是否包含PII."""
        return len(self.detect(text)) > 0

    def mask(self, text: str, pii_type: str = None) -> str:
        """部分脱敏（保留部分信息）.

        例如：email -> a***@example.com
        """
        if not text:
            return text

        # Email部分脱敏
        if pii_type == "email" or (pii_type is None and "@" in text):
            parts = text.split("@")
            if len(parts) == 2:
                local = parts[0]
                if len(local) > 2:
                    return f"{local[0]}{'*' * (len(local) - 2)}{local[-1]}@{parts[1]}"

        # 身份证部分脱敏
        if pii_type == "id_card" or (pii_type is None and len(text) == 18):
            return f"{text[:6]}{'*' * 8}{text[14:]}"

        # 手机号部分脱敏
        if pii_type == "phone" or (pii_type is None and len(text) == 11):
            return f"{text[:3]}{'*' * 4}{text[7:]}"

        return self.sanitize(text)
