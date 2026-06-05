"""NEXUS异常模块.

导出所有异常类和错误码枚举。
"""

from typing import Optional, Dict, Any

# 从error_codes导入错误码相关
from nexus.exceptions.error_codes import (
    NexusErrorCode,
    ERROR_CODE_TO_HTTP_STATUS,
    get_http_status_for_error_code,
    get_error_code_description,
)


class NexusException(Exception):
    """NEXUS基础异常.
    
    支持结构化错误码和详细信息，用于统一的错误响应格式。
    
    Attributes:
        message: 错误消息
        error_code: 错误码枚举值
        status_code: HTTP状态码（可从error_code自动推导）
        details: 额外的错误详情字典
        code: 向后兼容的字符串错误码（已废弃，建议使用error_code）
    """

    def __init__(
        self,
        message: str,
        error_code: Optional[NexusErrorCode] = None,
        status_code: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
        code: Optional[str] = None,  # 向后兼容
    ):
        """初始化NexusException.
        
        Args:
            message: 错误描述消息
            error_code: 错误码枚举值，如未提供则默认为INTERNAL_SERVER_ERROR
            status_code: HTTP状态码，如未提供则从error_code自动推导
            details: 额外的错误详情，将包含在响应中
            code: [已废弃] 字符串错误码，仅用于向后兼容
        """
        self.message = message
        self.error_code = error_code or NexusErrorCode.INTERNAL_SERVER_ERROR
        self.status_code = status_code or get_http_status_for_error_code(self.error_code)
        self.details = details or {}
        
        # 向后兼容：保留code属性
        if code:
            self.code = code
        else:
            # 从error_code生成字符串形式的code
            self.code = self.error_code.name
        
        super().__init__(self.message)


# 工作流异常
class WorkflowException(NexusException):
    """工作流相关异常."""
    pass


class WorkflowNotFoundException(WorkflowException):
    """工作流不存在."""

    status_code = 404

    def __init__(self, workflow_id: str):
        super().__init__(
            message=f"Workflow '{workflow_id}' not found",
            code="WORKFLOW_NOT_FOUND",
        )


class WorkflowValidationException(WorkflowException):
    """工作流验证失败."""
    pass


class WorkflowExecutionException(WorkflowException):
    """工作流执行异常."""
    pass


class CircularDependencyException(WorkflowValidationException):
    """工作流存在循环依赖."""

    status_code = 422

    def __init__(self, node_ids: list[str]):
        super().__init__(
            message=f"Circular dependency detected: {' -> '.join(node_ids)}",
            code="CIRCULAR_DEPENDENCY",
        )


# 执行异常
class RunException(NexusException):
    """执行实例相关异常."""
    pass


class RunNotFoundException(RunException):
    """执行实例不存在."""

    status_code = 404

    def __init__(self, run_id: str):
        super().__init__(
            message=f"Run '{run_id}' not found",
            code="RUN_NOT_FOUND",
        )


class CheckpointNotFoundException(RunException):
    """检查点不存在."""

    status_code = 404

    def __init__(self, run_id: str):
        super().__init__(
            message=f"No checkpoint found for run '{run_id}'",
            code="CHECKPOINT_NOT_FOUND",
        )


# Agent异常
class AgentException(NexusException):
    """Agent相关异常."""
    pass


class AgentNotFoundException(AgentException):
    """Agent不存在."""

    status_code = 404

    def __init__(self, agent_id: str):
        super().__init__(
            message=f"Agent '{agent_id}' not found",
            code="AGENT_NOT_FOUND",
        )


class LLMCallException(AgentException):
    """LLM调用失败."""

    status_code = 502

    def __init__(self, message: str, provider: str = ""):
        super().__init__(
            message=f"LLM call failed{' [' + provider + ']' if provider else ''}: {message}",
            code="LLM_CALL_FAILED",
        )


class MaxIterationsReachedException(AgentException):
    """Agent达到最大迭代次数."""

    status_code = 422

    def __init__(self, agent_name: str, max_iterations: int):
        super().__init__(
            message=f"Agent '{agent_name}' reached max iterations ({max_iterations})",
            code="MAX_ITERATIONS_REACHED",
        )


# 工具异常
class ToolException(NexusException):
    """工具相关异常."""
    pass


class ToolNotFoundException(ToolException):
    """工具不存在."""

    status_code = 404

    def __init__(self, tool_name: str):
        super().__init__(
            message=f"Tool '{tool_name}' not found",
            code="TOOL_NOT_FOUND",
        )


class ToolPermissionDeniedException(ToolException):
    """工具权限不足."""

    status_code = 403

    def __init__(self, tool_name: str):
        super().__init__(
            message=f"Permission denied for tool '{tool_name}'",
            code="TOOL_PERMISSION_DENIED",
        )


class ToolExecutionException(ToolException):
    """工具执行失败."""

    status_code = 502

    def __init__(self, tool_name: str, message: str):
        super().__init__(
            message=f"Tool '{tool_name}' execution failed: {message}",
            code="TOOL_EXECUTION_FAILED",
        )


# HITL异常
class HITLException(NexusException):
    """人工审批相关异常."""
    pass


class HITLTaskNotFoundException(HITLException):
    """审批任务不存在."""

    status_code = 404

    def __init__(self, task_id: str):
        super().__init__(
            message=f"HITL task '{task_id}' not found",
            code="HITL_TASK_NOT_FOUND",
        )


class HITLTimeoutException(HITLException):
    """审批任务超时."""

    status_code = 408

    def __init__(self, task_id: str):
        super().__init__(
            message=f"HITL task '{task_id}' timed out",
            code="HITL_TIMEOUT",
        )


# 安全异常
class SecurityException(NexusException):
    """安全相关异常."""
    pass


class AuthenticationException(SecurityException):
    """认证失败."""

    status_code = 401

    def __init__(self, message: str = "Authentication failed"):
        super().__init__(message=message, code="AUTHENTICATION_FAILED")


class AuthorizationException(SecurityException):
    """授权失败."""

    status_code = 403

    def __init__(self, message: str = "Permission denied"):
        super().__init__(message=message, code="AUTHORIZATION_FAILED")


class PermissionDeniedException(SecurityException):
    """权限不足."""

    status_code = 403

    def __init__(self, resource: str = "", action: str = ""):
        super().__init__(
            message=f"Permission denied: cannot {action} {resource}" if action and resource else "Permission denied",
            code="PERMISSION_DENIED",
        )


# 租户异常
class TenantException(NexusException):
    """租户相关异常."""
    pass


class TenantNotFoundException(TenantException):
    """租户不存在."""

    status_code = 404

    def __init__(self, tenant_id: str):
        super().__init__(
            message=f"Tenant '{tenant_id}' not found",
            code="TENANT_NOT_FOUND",
        )


__all__ = [
    # 错误码
    "NexusErrorCode",
    "ERROR_CODE_TO_HTTP_STATUS",
    "get_http_status_for_error_code",
    "get_error_code_description",
    # 基础异常
    "NexusException",
    # 工作流异常
    "WorkflowException",
    "WorkflowNotFoundException",
    "WorkflowValidationException",
    "WorkflowExecutionException",
    "CircularDependencyException",
    # 执行异常
    "RunException",
    "RunNotFoundException",
    "CheckpointNotFoundException",
    # Agent异常
    "AgentException",
    "AgentNotFoundException",
    "LLMCallException",
    "MaxIterationsReachedException",
    # 工具异常
    "ToolException",
    "ToolNotFoundException",
    "ToolPermissionDeniedException",
    "ToolExecutionException",
    # HITL异常
    "HITLException",
    "HITLTaskNotFoundException",
    "HITLTimeoutException",
    # 安全异常
    "SecurityException",
    "AuthenticationException",
    "AuthorizationException",
    "PermissionDeniedException",
    # 租户异常
    "TenantException",
    "TenantNotFoundException",
]
