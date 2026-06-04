# NEXUS 错误码快速参考

## 响应格式

```json
{
  "success": false,
  "error": {
    "code": 1101,
    "name": "WORKFLOW_NOT_FOUND",
    "message": "Workflow not found",
    "details": {}
  }
}
```

## 错误码速查表

### 认证授权 (1001-1006)
| Code | Name | HTTP | Description |
|------|------|------|-------------|
| 1001 | AUTH_INVALID_TOKEN | 401 | 无效的访问令牌 |
| 1002 | AUTH_TOKEN_EXPIRED | 401 | 令牌已过期 |
| 1003 | AUTH_INSUFFICIENT_PERMISSIONS | 403 | 权限不足 |
| 1004 | AUTH_API_KEY_INVALID | 401 | 无效的API密钥 |
| 1005 | AUTH_API_KEY_EXPIRED | 401 | API密钥已过期 |
| 1006 | AUTH_RATE_LIMIT_EXCEEDED | 429 | 超过速率限制 |

### 工作流引擎 (1101-1108)
| Code | Name | HTTP | Description |
|------|------|------|-------------|
| 1101 | WORKFLOW_NOT_FOUND | 404 | 工作流不存在 |
| 1102 | WORKFLOW_INVALID_DEFINITION | 422 | 工作流定义无效 |
| 1103 | WORKFLOW_CIRCULAR_DEPENDENCY | 422 | 循环依赖 |
| 1104 | WORKFLOW_EXECUTION_TIMEOUT | 408 | 执行超时 |
| 1105 | WORKFLOW_MAX_STEPS_EXCEEDED | 422 | 超出最大步骤 |
| 1106 | WORKFLOW_NODE_FAILED | 500 | 节点执行失败 |
| 1107 | WORKFLOW_VALIDATION_FAILED | 422 | 验证失败 |
| 1108 | WORKFLOW_CHECKPOINT_NOT_FOUND | 404 | 检查点不存在 |

### Agent系统 (1201-1206)
| Code | Name | HTTP | Description |
|------|------|------|-------------|
| 1201 | AGENT_NOT_FOUND | 404 | Agent不存在 |
| 1202 | AGENT_EXECUTION_FAILED | 500 | Agent执行失败 |
| 1203 | AGENT_LLM_CALL_FAILED | 502 | LLM调用失败 |
| 1204 | AGENT_TOOL_NOT_FOUND | 404 | 工具不存在 |
| 1205 | AGENT_CONCURRENCY_LIMIT | 429 | 并发限制 |
| 1206 | AGENT_MAX_ITERATIONS_REACHED | 422 | 达到最大迭代 |

### 数据库 (1301-1304)
| Code | Name | HTTP | Description |
|------|------|------|-------------|
| 1301 | DB_CONNECTION_FAILED | 503 | 连接失败 |
| 1302 | DB_QUERY_ERROR | 503 | 查询错误 |
| 1303 | DB_DUPLICATE_ENTRY | 409 | 重复条目 |
| 1304 | DB_INTEGRITY_VIOLATION | 422 | 完整性违反 |

### 参数校验 (1401-1404)
| Code | Name | HTTP | Description |
|------|------|------|-------------|
| 1401 | VALIDATION_INVALID_INPUT | 400 | 无效输入 |
| 1402 | VALIDATION_MISSING_FIELD | 422 | 缺少字段 |
| 1403 | VALIDATION_TYPE_MISMATCH | 422 | 类型不匹配 |
| 1404 | VALIDATION_VALUE_OUT_OF_RANGE | 422 | 值超出范围 |

### 内部服务 (1500-1504)
| Code | Name | HTTP | Description |
|------|------|------|-------------|
| 1500 | INTERNAL_SERVER_ERROR | 500 | 内部错误 |
| 1501 | SERVICE_UNAVAILABLE | 503 | 服务不可用 |
| 1502 | EXTERNAL_SERVICE_TIMEOUT | 504 | 外部超时 |
| 1503 | MCP_CONNECTION_FAILED | 503 | MCP连接失败 |
| 1504 | REDIS_CONNECTION_FAILED | 503 | Redis连接失败 |

### HITL审批 (1601-1603)
| Code | Name | HTTP | Description |
|------|------|------|-------------|
| 1601 | HITL_TASK_NOT_FOUND | 404 | 任务不存在 |
| 1602 | HITL_TIMEOUT | 408 | 任务超时 |
| 1603 | HITL_INVALID_ACTION | 422 | 操作无效 |

### 工具执行 (1701-1704)
| Code | Name | HTTP | Description |
|------|------|------|-------------|
| 1701 | TOOL_NOT_FOUND | 404 | 工具不存在 |
| 1702 | TOOL_PERMISSION_DENIED | 403 | 权限不足 |
| 1703 | TOOL_EXECUTION_FAILED | 500 | 执行失败 |
| 1704 | TOOL_TIMEOUT | 504 | 执行超时 |

### 租户权限 (1801-1803)
| Code | Name | HTTP | Description |
|------|------|------|-------------|
| 1801 | TENANT_NOT_FOUND | 404 | 租户不存在 |
| 1802 | TENANT_ACCESS_DENIED | 403 | 访问被拒绝 |
| 1803 | PERMISSION_DENIED | 403 | 权限被拒绝 |

## 代码示例

### Python抛出异常

```python
from nexus.exceptions import NexusException, NexusErrorCode

raise NexusException(
    message="Workflow not found",
    error_code=NexusErrorCode.WORKFLOW_NOT_FOUND,
    details={"workflow_id": "wf_123"}
)
```

### JavaScript/TypeScript处理

```typescript
try {
  const response = await fetch('/api/v1/workflows/wf_123');
  const data = await response.json();
  
  if (!data.success) {
    console.error(`Error ${data.error.code}: ${data.error.message}`);
    
    // 根据错误码处理
    switch (data.error.code) {
      case 1101: // WORKFLOW_NOT_FOUND
        showNotFoundPage();
        break;
      case 1001: // AUTH_INVALID_TOKEN
        redirectToLogin();
        break;
      default:
        showError(data.error.message);
    }
  }
} catch (error) {
  console.error('Request failed:', error);
}
```

### 重试策略

```python
import asyncio
from nexus.exceptions import NexusErrorCode

async def call_with_retry(func, max_retries=3):
    """对可重试错误进行指数退避重试."""
    retryable_codes = {
        NexusErrorCode.AGENT_LLM_CALL_FAILED,
        NexusErrorCode.DB_CONNECTION_FAILED,
        NexusErrorCode.SERVICE_UNAVAILABLE,
        NexusErrorCode.EXTERNAL_SERVICE_TIMEOUT,
    }
    
    for attempt in range(max_retries):
        try:
            return await func()
        except NexusException as e:
            if e.error_code not in retryable_codes:
                raise  # 不可重试的错误直接抛出
            
            if attempt == max_retries - 1:
                raise  # 最后一次尝试，重新抛出
            
            delay = 2 ** attempt  # 指数退避
            await asyncio.sleep(delay)
```

## HTTP状态码映射

- **4xx**: 客户端错误（认证、参数、权限）
- **5xx**: 服务器错误（内部错误、服务不可用、超时）
- **409**: 冲突（数据库重复）
- **429**: 限流（速率限制、并发限制）

## 最佳实践

1. ✅ 始终使用 `NexusErrorCode` 枚举
2. ✅ 在 `details` 中提供调试信息
3. ✅ 让系统自动推导HTTP状态码
4. ✅ 记录完整的错误上下文
5. ❌ 不要硬编码错误码数字
6. ❌ 不要在错误消息中暴露敏感信息
7. ❌ 不要忽略异常链（使用 `raise ... from e`）

---

完整文档请参考: [README.md - 错误码参考](../README.md#错误码参考)
