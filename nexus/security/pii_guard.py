"""PII检测与脱敏.

借鉴Portkey Guardrails设计。
"""

import re
from dataclasses import dataclass
from typing import List


@dataclass
class PIIFinding:
    """PII发现结果."""

    type: str
    start: int
    end: int
    value: str


class PIIGuard:
    """PII检测与脱敏.

    检测并脱敏个人身份信息。
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

    def sanitize(self, text: str) -> str:
        """脱敏处理.

        将所有PII替换为 [TYPE_REDACTED]。
        """
        if not text:
            return text

        for pii_type, pattern in self.PII_PATTERNS.items():
            text = re.sub(pattern, f"[{pii_type.upper()}_REDACTED]", text, flags=re.IGNORECASE)
        return text

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
