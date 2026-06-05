"""NEXUS系统错误码定义.

错误码规范:
- 格式: NEXUS_XXX (3位数字)
- 范围: 001-999
- 分类:
  - 001-099: 认证授权错误
  - 100-199: 工作流引擎错误
  - 200-299: Agent系统错误
  - 300-399: 数据库错误
  - 400-499: 参数校验错误
  - 500-599: 内部服务错误
  - 600-699: HITL审批错误
  - 700-799: 工具执行错误
  - 800-899: 租户与权限错误
  - 900-999: 预留扩展
"""

from enum import IntEnum


class NexusErrorCode(IntEnum):
    """NEXUS系统错误码枚举.
    
    使用示例:
        raise NexusException(
            message="Invalid token",
            error_code=NexusErrorCode.AUTH_INVALID_TOKEN,
            status_code=401
        )
    """
    
    # ==================== 001-099: 认证授权错误 ====================
    AUTH_INVALID_TOKEN = 1001
    """无效的访问令牌"""
    
    AUTH_TOKEN_EXPIRED = 1002
    """访问令牌已过期"""
    
    AUTH_INSUFFICIENT_PERMISSIONS = 1003
    """权限不足"""
    
    AUTH_API_KEY_INVALID = 1004
    """无效的API密钥"""
    
    AUTH_API_KEY_EXPIRED = 1005
    """API密钥已过期"""
    
    AUTH_RATE_LIMIT_EXCEEDED = 1006
    """超过速率限制"""
    
    # ==================== 100-199: 工作流引擎错误 ====================
    WORKFLOW_NOT_FOUND = 1101
    """工作流不存在"""
    
    WORKFLOW_INVALID_DEFINITION = 1102
    """工作流定义无效"""
    
    WORKFLOW_CIRCULAR_DEPENDENCY = 1103
    """工作流存在循环依赖"""
    
    WORKFLOW_EXECUTION_TIMEOUT = 1104
    """工作流执行超时"""
    
    WORKFLOW_MAX_STEPS_EXCEEDED = 1105
    """工作流超出最大步骤数"""
    
    WORKFLOW_NODE_FAILED = 1106
    """工作流节点执行失败"""
    
    WORKFLOW_VALIDATION_FAILED = 1107
    """工作流验证失败"""
    
    WORKFLOW_CHECKPOINT_NOT_FOUND = 1108
    """工作流检查点不存在"""
    
    # ==================== 200-299: Agent系统错误 ====================
    AGENT_NOT_FOUND = 1201
    """Agent不存在"""
    
    AGENT_EXECUTION_FAILED = 1202
    """Agent执行失败"""
    
    AGENT_LLM_CALL_FAILED = 1203
    """Agent调用LLM失败"""
    
    AGENT_TOOL_NOT_FOUND = 1204
    """Agent工具不存在"""
    
    AGENT_CONCURRENCY_LIMIT = 1205
    """Agent并发限制"""
    
    AGENT_MAX_ITERATIONS_REACHED = 1206
    """Agent达到最大迭代次数"""
    
    # ==================== 300-399: 数据库错误 ====================
    DB_CONNECTION_FAILED = 1301
    """数据库连接失败"""
    
    DB_QUERY_ERROR = 1302
    """数据库查询错误"""
    
    DB_DUPLICATE_ENTRY = 1303
    """数据库重复条目"""
    
    DB_INTEGRITY_VIOLATION = 1304
    """数据库完整性约束违反"""
    
    # ==================== 400-499: 参数校验错误 ====================
    VALIDATION_INVALID_INPUT = 1401
    """无效的输入参数"""
    
    VALIDATION_MISSING_FIELD = 1402
    """缺少必填字段"""
    
    VALIDATION_TYPE_MISMATCH = 1403
    """类型不匹配"""
    
    VALIDATION_VALUE_OUT_OF_RANGE = 1404
    """值超出范围"""
    
    # ==================== 500-599: 内部服务错误 ====================
    INTERNAL_SERVER_ERROR = 1500
    """内部服务器错误"""
    
    SERVICE_UNAVAILABLE = 1501
    """服务不可用"""
    
    EXTERNAL_SERVICE_TIMEOUT = 1502
    """外部服务超时"""
    
    MCP_CONNECTION_FAILED = 1503
    """MCP连接失败"""
    
    REDIS_CONNECTION_FAILED = 1504
    """Redis连接失败"""
    
    # ==================== 600-699: HITL审批错误 ====================
    HITL_TASK_NOT_FOUND = 1601
    """HITL任务不存在"""
    
    HITL_TIMEOUT = 1602
    """HITL任务超时"""
    
    HITL_INVALID_ACTION = 1603
    """HITL操作无效"""
    
    # ==================== 700-799: 工具执行错误 ====================
    TOOL_NOT_FOUND = 1701
    """工具不存在"""
    
    TOOL_PERMISSION_DENIED = 1702
    """工具权限不足"""
    
    TOOL_EXECUTION_FAILED = 1703
    """工具执行失败"""
    
    TOOL_TIMEOUT = 1704
    """工具执行超时"""
    
    # ==================== 800-899: 租户与权限错误 ====================
    TENANT_NOT_FOUND = 1801
    """租户不存在"""
    
    TENANT_ACCESS_DENIED = 1802
    """租户访问被拒绝"""
    
    PERMISSION_DENIED = 1803
    """权限被拒绝"""
    
    # ==================== 900-999: 预留扩展 ====================
    RESERVED_FOR_FUTURE_USE = 1900
    """预留给未来使用"""


# 错误码到HTTP状态码的映射
ERROR_CODE_TO_HTTP_STATUS = {
    # 认证授权错误 -> 401/403
    NexusErrorCode.AUTH_INVALID_TOKEN: 401,
    NexusErrorCode.AUTH_TOKEN_EXPIRED: 401,
    NexusErrorCode.AUTH_INSUFFICIENT_PERMISSIONS: 403,
    NexusErrorCode.AUTH_API_KEY_INVALID: 401,
    NexusErrorCode.AUTH_API_KEY_EXPIRED: 401,
    NexusErrorCode.AUTH_RATE_LIMIT_EXCEEDED: 429,
    
    # 工作流引擎错误 -> 404/422/500
    NexusErrorCode.WORKFLOW_NOT_FOUND: 404,
    NexusErrorCode.WORKFLOW_INVALID_DEFINITION: 422,
    NexusErrorCode.WORKFLOW_CIRCULAR_DEPENDENCY: 422,
    NexusErrorCode.WORKFLOW_EXECUTION_TIMEOUT: 408,
    NexusErrorCode.WORKFLOW_MAX_STEPS_EXCEEDED: 422,
    NexusErrorCode.WORKFLOW_NODE_FAILED: 500,
    NexusErrorCode.WORKFLOW_VALIDATION_FAILED: 422,
    NexusErrorCode.WORKFLOW_CHECKPOINT_NOT_FOUND: 404,
    
    # Agent系统错误 -> 404/500/502
    NexusErrorCode.AGENT_NOT_FOUND: 404,
    NexusErrorCode.AGENT_EXECUTION_FAILED: 500,
    NexusErrorCode.AGENT_LLM_CALL_FAILED: 502,
    NexusErrorCode.AGENT_TOOL_NOT_FOUND: 404,
    NexusErrorCode.AGENT_CONCURRENCY_LIMIT: 429,
    NexusErrorCode.AGENT_MAX_ITERATIONS_REACHED: 422,
    
    # 数据库错误 -> 503
    NexusErrorCode.DB_CONNECTION_FAILED: 503,
    NexusErrorCode.DB_QUERY_ERROR: 503,
    NexusErrorCode.DB_DUPLICATE_ENTRY: 409,
    NexusErrorCode.DB_INTEGRITY_VIOLATION: 422,
    
    # 参数校验错误 -> 400/422
    NexusErrorCode.VALIDATION_INVALID_INPUT: 400,
    NexusErrorCode.VALIDATION_MISSING_FIELD: 422,
    NexusErrorCode.VALIDATION_TYPE_MISMATCH: 422,
    NexusErrorCode.VALIDATION_VALUE_OUT_OF_RANGE: 422,
    
    # 内部服务错误 -> 500/502/503
    NexusErrorCode.INTERNAL_SERVER_ERROR: 500,
    NexusErrorCode.SERVICE_UNAVAILABLE: 503,
    NexusErrorCode.EXTERNAL_SERVICE_TIMEOUT: 504,
    NexusErrorCode.MCP_CONNECTION_FAILED: 503,
    NexusErrorCode.REDIS_CONNECTION_FAILED: 503,
    
    # HITL审批错误 -> 404/408/422
    NexusErrorCode.HITL_TASK_NOT_FOUND: 404,
    NexusErrorCode.HITL_TIMEOUT: 408,
    NexusErrorCode.HITL_INVALID_ACTION: 422,
    
    # 工具执行错误 -> 404/403/500/504
    NexusErrorCode.TOOL_NOT_FOUND: 404,
    NexusErrorCode.TOOL_PERMISSION_DENIED: 403,
    NexusErrorCode.TOOL_EXECUTION_FAILED: 500,
    NexusErrorCode.TOOL_TIMEOUT: 504,
    
    # 租户与权限错误 -> 404/403
    NexusErrorCode.TENANT_NOT_FOUND: 404,
    NexusErrorCode.TENANT_ACCESS_DENIED: 403,
    NexusErrorCode.PERMISSION_DENIED: 403,
}


def get_http_status_for_error_code(error_code: NexusErrorCode) -> int:
    """根据错误码获取对应的HTTP状态码.
    
    Args:
        error_code: NexusErrorCode枚举值
        
    Returns:
        HTTP状态码，默认返回500
    """
    return ERROR_CODE_TO_HTTP_STATUS.get(error_code, 500)


def get_error_code_description(error_code: NexusErrorCode) -> str:
    """获取错误码的描述信息.
    
    Args:
        error_code: NexusErrorCode枚举值
        
    Returns:
        错误码的中文描述
    """
    descriptions = {
        NexusErrorCode.AUTH_INVALID_TOKEN: "无效的访问令牌",
        NexusErrorCode.AUTH_TOKEN_EXPIRED: "访问令牌已过期",
        NexusErrorCode.AUTH_INSUFFICIENT_PERMISSIONS: "权限不足",
        NexusErrorCode.AUTH_API_KEY_INVALID: "无效的API密钥",
        NexusErrorCode.AUTH_API_KEY_EXPIRED: "API密钥已过期",
        NexusErrorCode.AUTH_RATE_LIMIT_EXCEEDED: "超过速率限制",
        NexusErrorCode.WORKFLOW_NOT_FOUND: "工作流不存在",
        NexusErrorCode.WORKFLOW_INVALID_DEFINITION: "工作流定义无效",
        NexusErrorCode.WORKFLOW_CIRCULAR_DEPENDENCY: "工作流存在循环依赖",
        NexusErrorCode.WORKFLOW_EXECUTION_TIMEOUT: "工作流执行超时",
        NexusErrorCode.WORKFLOW_MAX_STEPS_EXCEEDED: "工作流超出最大步骤数",
        NexusErrorCode.WORKFLOW_NODE_FAILED: "工作流节点执行失败",
        NexusErrorCode.WORKFLOW_VALIDATION_FAILED: "工作流验证失败",
        NexusErrorCode.WORKFLOW_CHECKPOINT_NOT_FOUND: "工作流检查点不存在",
        NexusErrorCode.AGENT_NOT_FOUND: "Agent不存在",
        NexusErrorCode.AGENT_EXECUTION_FAILED: "Agent执行失败",
        NexusErrorCode.AGENT_LLM_CALL_FAILED: "Agent调用LLM失败",
        NexusErrorCode.AGENT_TOOL_NOT_FOUND: "Agent工具不存在",
        NexusErrorCode.AGENT_CONCURRENCY_LIMIT: "Agent并发限制",
        NexusErrorCode.AGENT_MAX_ITERATIONS_REACHED: "Agent达到最大迭代次数",
        NexusErrorCode.DB_CONNECTION_FAILED: "数据库连接失败",
        NexusErrorCode.DB_QUERY_ERROR: "数据库查询错误",
        NexusErrorCode.DB_DUPLICATE_ENTRY: "数据库重复条目",
        NexusErrorCode.DB_INTEGRITY_VIOLATION: "数据库完整性约束违反",
        NexusErrorCode.VALIDATION_INVALID_INPUT: "无效的输入参数",
        NexusErrorCode.VALIDATION_MISSING_FIELD: "缺少必填字段",
        NexusErrorCode.VALIDATION_TYPE_MISMATCH: "类型不匹配",
        NexusErrorCode.VALIDATION_VALUE_OUT_OF_RANGE: "值超出范围",
        NexusErrorCode.INTERNAL_SERVER_ERROR: "内部服务器错误",
        NexusErrorCode.SERVICE_UNAVAILABLE: "服务不可用",
        NexusErrorCode.EXTERNAL_SERVICE_TIMEOUT: "外部服务超时",
        NexusErrorCode.MCP_CONNECTION_FAILED: "MCP连接失败",
        NexusErrorCode.REDIS_CONNECTION_FAILED: "Redis连接失败",
        NexusErrorCode.HITL_TASK_NOT_FOUND: "HITL任务不存在",
        NexusErrorCode.HITL_TIMEOUT: "HITL任务超时",
        NexusErrorCode.HITL_INVALID_ACTION: "HITL操作无效",
        NexusErrorCode.TOOL_NOT_FOUND: "工具不存在",
        NexusErrorCode.TOOL_PERMISSION_DENIED: "工具权限不足",
        NexusErrorCode.TOOL_EXECUTION_FAILED: "工具执行失败",
        NexusErrorCode.TOOL_TIMEOUT: "工具执行超时",
        NexusErrorCode.TENANT_NOT_FOUND: "租户不存在",
        NexusErrorCode.TENANT_ACCESS_DENIED: "租户访问被拒绝",
        NexusErrorCode.PERMISSION_DENIED: "权限被拒绝",
    }
    return descriptions.get(error_code, "未知错误")
