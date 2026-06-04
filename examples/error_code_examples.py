"""NEXUS错误码体系使用示例.

演示如何在不同场景下使用新的错误码体系。
"""

import asyncio
from nexus.exceptions import NexusException, NexusErrorCode
from nexus.exceptions.error_codes import get_error_code_description


# ============================================================================
# 示例1: 基础用法 - 抛出带错误码的异常
# ============================================================================

def example_basic_usage():
    """基础用法示例."""
    
    # 简单抛出异常（自动推导HTTP状态码）
    try:
        raise NexusException(
            message="Workflow not found",
            error_code=NexusErrorCode.WORKFLOW_NOT_FOUND,
            details={"workflow_id": "wf_123"}
        )
    except NexusException as e:
        print(f"Error Code: {e.error_code.value}")
        print(f"Error Name: {e.code}")
        print(f"HTTP Status: {e.status_code}")
        print(f"Message: {e.message}")
        print(f"Details: {e.details}")
        print()


# ============================================================================
# 示例2: 工作流引擎中的错误处理
# ============================================================================

async def example_workflow_error_handling():
    """工作流引擎错误处理示例."""
    
    from nexus.engine.workflow_engine import WorkflowEngine
    from nexus.exceptions import WorkflowExecutionException
    
    async def execute_workflow(workflow_id: str):
        """模拟工作流执行."""
        if workflow_id == "invalid":
            # 工作流不存在
            raise NexusException(
                message=f"Workflow '{workflow_id}' not found",
                error_code=NexusErrorCode.WORKFLOW_NOT_FOUND,
                details={"workflow_id": workflow_id}
            )
        
        # 模拟执行超时
        await asyncio.sleep(0.1)
        raise NexusException(
            message="Workflow execution timeout",
            error_code=NexusErrorCode.WORKFLOW_EXECUTION_TIMEOUT,
            details={
                "workflow_id": workflow_id,
                "timeout_seconds": 300
            }
        )
    
    # 测试
    try:
        await execute_workflow("invalid")
    except NexusException as e:
        print(f"[Workflow Error] {e.error_code.name}: {e.message}")
        print(f"  Details: {e.details}")
        print()


# ============================================================================
# 示例3: Agent系统中的错误处理
# ============================================================================

async def example_agent_error_handling():
    """Agent系统错误处理示例."""
    
    async def call_llm(prompt: str):
        """模拟LLM调用."""
        # 模拟LLM调用失败
        raise NexusException(
            message="LLM API returned 503 error",
            error_code=NexusErrorCode.AGENT_LLM_CALL_FAILED,
            details={
                "provider": "openai",
                "model": "gpt-4",
                "http_status": 503
            }
        )
    
    try:
        await call_llm("Hello")
    except NexusException as e:
        print(f"[Agent Error] {e.error_code.name}: {e.message}")
        print(f"  Provider: {e.details.get('provider')}")
        print(f"  Model: {e.details.get('model')}")
        print()


# ============================================================================
# 示例4: 数据库错误处理
# ============================================================================

async def example_database_error_handling():
    """数据库错误处理示例."""
    
    async def query_database(query: str):
        """模拟数据库查询."""
        # 模拟数据库连接失败
        raise NexusException(
            message="Failed to connect to database",
            error_code=NexusErrorCode.DB_CONNECTION_FAILED,
            details={
                "host": "localhost",
                "port": 5432,
                "database": "nexus"
            }
        )
    
    try:
        await query_database("SELECT * FROM workflows")
    except NexusException as e:
        print(f"[Database Error] {e.error_code.name}: {e.message}")
        print(f"  Connection: {e.details.get('host')}:{e.details.get('port')}")
        print()


# ============================================================================
# 示例5: 参数校验错误
# ============================================================================

def example_validation_error():
    """参数校验错误示例."""
    
    def validate_workflow_definition(defn: dict):
        """验证工作流定义."""
        if "nodes" not in defn:
            raise NexusException(
                message="Missing required field: nodes",
                error_code=NexusErrorCode.VALIDATION_MISSING_FIELD,
                details={"field": "nodes"}
            )
        
        if not isinstance(defn.get("nodes"), list):
            raise NexusException(
                message="Field 'nodes' must be a list",
                error_code=NexusErrorCode.VALIDATION_TYPE_MISMATCH,
                details={
                    "field": "nodes",
                    "expected": "list",
                    "actual": type(defn.get("nodes")).__name__
                }
            )
    
    try:
        validate_workflow_definition({"name": "test"})
    except NexusException as e:
        print(f"[Validation Error] {e.error_code.name}: {e.message}")
        print(f"  Field: {e.details.get('field')}")
        print()


# ============================================================================
# 示例6: 工具执行错误
# ============================================================================

async def example_tool_error():
    """工具执行错误示例."""
    
    async def execute_tool(tool_name: str, params: dict):
        """模拟工具执行."""
        if tool_name == "nonexistent":
            raise NexusException(
                message=f"Tool '{tool_name}' not found",
                error_code=NexusErrorCode.TOOL_NOT_FOUND,
                details={"tool_name": tool_name}
            )
        
        # 模拟工具执行失败
        raise NexusException(
            message="Tool execution failed",
            error_code=NexusErrorCode.TOOL_EXECUTION_FAILED,
            details={
                "tool_name": tool_name,
                "error": "Connection timeout"
            }
        )
    
    try:
        await execute_tool("web_search", {"query": "AI"})
    except NexusException as e:
        print(f"[Tool Error] {e.error_code.name}: {e.message}")
        print(f"  Tool: {e.details.get('tool_name')}")
        print()


# ============================================================================
# 示例7: 认证授权错误
# ============================================================================

def example_auth_error():
    """认证授权错误示例."""
    
    def authenticate(token: str):
        """模拟认证."""
        if not token:
            raise NexusException(
                message="Authentication token is required",
                error_code=NexusErrorCode.AUTH_INVALID_TOKEN
            )
        
        if token == "expired":
            raise NexusException(
                message="Token has expired",
                error_code=NexusErrorCode.AUTH_TOKEN_EXPIRED,
                details={"expired_at": "2024-01-01T00:00:00Z"}
            )
    
    try:
        authenticate("")
    except NexusException as e:
        print(f"[Auth Error] {e.error_code.name}: {e.message}")
        print()


# ============================================================================
# 示例8: 获取错误码描述
# ============================================================================

def example_error_code_description():
    """获取错误码描述示例."""
    
    error_codes = [
        NexusErrorCode.WORKFLOW_NOT_FOUND,
        NexusErrorCode.AGENT_LLM_CALL_FAILED,
        NexusErrorCode.DB_CONNECTION_FAILED,
    ]
    
    print("Error Code Descriptions:")
    for code in error_codes:
        description = get_error_code_description(code)
        print(f"  {code.value} ({code.name}): {description}")
    print()


# ============================================================================
# 示例9: 向后兼容 - 使用旧的code参数
# ============================================================================

def example_backward_compatibility():
    """向后兼容示例."""
    
    # 旧的方式仍然有效
    try:
        raise NexusException(
            message="Legacy error",
            code="LEGACY_ERROR_CODE"
        )
    except NexusException as e:
        print(f"[Legacy] Code: {e.code}, Message: {e.message}")
        print(f"  Auto-assigned error_code: {e.error_code.name}")
        print()


# ============================================================================
# 主函数 - 运行所有示例
# ============================================================================

async def main():
    """运行所有示例."""
    print("=" * 80)
    print("NEXUS 错误码体系使用示例")
    print("=" * 80)
    print()
    
    # 同步示例
    example_basic_usage()
    example_validation_error()
    example_auth_error()
    example_error_code_description()
    example_backward_compatibility()
    
    # 异步示例
    await example_workflow_error_handling()
    await example_agent_error_handling()
    await example_database_error_handling()
    await example_tool_error()
    
    print("=" * 80)
    print("所有示例运行完成！")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
