"""HTTP request tool — make GET/POST/PUT/DELETE requests."""
import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

import httpx
from nexus.exceptions import ToolExecutionException
from nexus.tools.registry import ToolRegistry, Tool, ToolResult, ToolType


# 修复 (S4-2): 阻止 SSRF 到内网 / metadata endpoint。
# 这些 CIDR 包含云厂商 metadata、loopback、私网 IP，
# 攻击者构造 `http://169.254.169.254/...` 偷 AWS/GCP/Azure metadata。
_BLOCKED_CIDRS = [
    ipaddress.ip_network("0.0.0.0/8"),  # "this network"
    ipaddress.ip_network("127.0.0.0/8"),  # loopback
    ipaddress.ip_network("10.0.0.0/8"),  # RFC1918
    ipaddress.ip_network("172.16.0.0/12"),  # RFC1918
    ipaddress.ip_network("192.168.0.0/16"),  # RFC1918
    ipaddress.ip_network("169.254.0.0/16"),  # link-local + cloud metadata
    ipaddress.ip_network("100.64.0.0/10"),  # carrier-grade NAT
    ipaddress.ip_network("::1/128"),  # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),  # IPv6 unique local
    ipaddress.ip_network("fe80::/10"),  # IPv6 link-local
]

# 修复 (S4-2): 工具硬上限 timeout，防止 LLM 配 params.timeout=99999 卡死事件循环
_MAX_TIMEOUT_SECONDS = 60.0
_DEFAULT_TIMEOUT_SECONDS = 30.0


async def _validate_url_safety(url: str) -> None:
    """验证 URL 协议 + 解析 host + 检查不在阻断 CIDR 中.

    Raises:
        ToolExecutionException: 协议非法或 host 解析到内网/loopback/metadata IP。
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ToolExecutionException(
            "http_request",
            f"URL scheme '{parsed.scheme}' not allowed (only http/https)",
        )
    if not parsed.hostname:
        raise ToolExecutionException("http_request", "URL has no hostname")

    # 解析 hostname（同步 dns 解析 → 这里用 getaddrinfo）
    try:
        # 强制 family=INET（IPv4），避免 v6 loopback ::1 走默认路径
        infos = await asyncio.get_event_loop().getaddrinfo(
            parsed.hostname, None, family=socket.AF_INET
        )
    except socket.gaierror as e:
        raise ToolExecutionException("http_request", f"DNS resolution failed: {e}") from e

    if not infos:
        raise ToolExecutionException("http_request", "DNS returned no addresses")

    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        for blocked in _BLOCKED_CIDRS:
            if ip in blocked:
                raise ToolExecutionException(
                    "http_request",
                    f"blocked private/internal IP {ip} (CIDR {blocked})",
                )


def create_http_tools(registry: ToolRegistry) -> None:
    async def http_request(params: dict, context: dict) -> ToolResult:
        """Make an HTTP request."""
        method = params.get("method", "GET")
        url = params["url"]
        headers = params.get("headers") or {}
        body = params.get("body") or {}
        timeout = params.get("timeout", _DEFAULT_TIMEOUT_SECONDS)

        # SSRF 防护：在发起请求前必须过 URL 安全检查
        await _validate_url_safety(url)

        # 硬上限 60s：params 里的 timeout 只允许 ≤ 60s
        try:
            effective_timeout = float(timeout)
        except (TypeError, ValueError):
            effective_timeout = _DEFAULT_TIMEOUT_SECONDS
        effective_timeout = min(max(effective_timeout, 1.0), _MAX_TIMEOUT_SECONDS)

        try:
            async with httpx.AsyncClient(timeout=effective_timeout) as client:
                if method.upper() == "GET":
                    resp = await client.get(url, headers=headers)
                elif method.upper() == "POST":
                    resp = await client.post(url, json=body, headers=headers)
                elif method.upper() == "PUT":
                    resp = await client.put(url, json=body, headers=headers)
                elif method.upper() == "DELETE":
                    resp = await client.delete(url, headers=headers)
                else:
                    return ToolResult(success=False, error=f"Unsupported method: {method}")
                return ToolResult(
                    success=True,
                    data={"status": resp.status_code, "body": resp.text[:5000]},
                )
        except ToolExecutionException:
            raise
        except Exception as e:
            # 网络错误（连接失败、超时）也归为 ToolExecutionException，
            # 避免向 LLM 暴露内部堆栈
            raise ToolExecutionException("http_request", str(e)) from e

    registry.register(Tool(
        name="http_request",
        description="Make HTTP requests (GET/POST/PUT/DELETE)",
        type=ToolType.PYTHON,
        schema={
            "type": "object",
            "properties": {
                "method": {"type": "string", "enum": ["GET", "POST", "PUT", "DELETE"]},
                "url": {"type": "string"},
                "headers": {"type": "object"},
                "body": {"type": "object"},
            },
            "required": ["method", "url"],
        },
        handler=http_request,
    ))
