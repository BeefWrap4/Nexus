"""NEXUS数据模型层.

基于WAT schema/*.py 升级：
- 从Pydantic数据模型迁移到SQLAlchemy ORM模型（数据库持久化）
- 保留Pydantic模型用于API序列化/反序列化
- 多租户支持
"""

from nexus.models.workflow import Workflow, WorkflowVersion, WorkflowRun, NodeRun
# 先导入 crew（含 CrewAgent），再导入 agent（引用 CrewAgent）避免 mapper 配置失败
from nexus.models.crew import Crew, CrewAgent, CrewRun
from nexus.models.agent import Agent
from nexus.models.tool import Tool
from nexus.models.hitl import HITLTask
from nexus.models.tenant import Tenant, User, APIKey
from nexus.models.system_setting import SystemSetting  # 修复 (P1): 租户级 KV 设置
from nexus.models.audit import AuditLog, Artifact
from nexus.models.eval import EvalRun
from nexus.models.experiment import PromptExperiment, PromptExperimentVariant
from nexus.models.llm_trace import LLMCallTrace
from nexus.models.prompt import PromptTemplate, PromptTemplateVersion
from nexus.models.billing import BillingSubscription, BillingUsageRecord
from nexus.models.subscription import Subscription
from nexus.models.invoice import Invoice
from nexus.models.quota_event import QuotaEvent

__all__ = [
    "Workflow",
    "WorkflowVersion",
    "WorkflowRun",
    "NodeRun",
    "Agent",
    "Crew",
    "CrewAgent",
    "CrewRun",
    "Tool",
    "HITLTask",
    "Tenant",
    "User",
    "APIKey",
    "SystemSetting",
    "AuditLog",
    "Artifact",
    "LLMCallTrace",
    "PromptTemplate",
    "PromptTemplateVersion",
    "PromptExperiment",
    "PromptExperimentVariant",
    "EvalRun",
    "BillingSubscription",
    "BillingUsageRecord",
    "Subscription",
    "Invoice",
    "QuotaEvent",
]