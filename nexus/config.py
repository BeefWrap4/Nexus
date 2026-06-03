"""NEXUS全局配置管理."""

import os
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """NEXUS应用配置."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 基础配置
    APP_NAME: str = "NEXUS"
    APP_VERSION: str = "0.1.0"
    ENVIRONMENT: str = Field(default="development", validation_alias="ENVIRONMENT")
    DEBUG: bool = Field(default=False, validation_alias="DEBUG")
    CORS_ALLOWED_ORIGINS: list[str] = Field(
        default_factory=list, validation_alias="CORS_ALLOWED_ORIGINS"
    )

    # 安全
    # NOTE: 生产环境必须设置强 SECRET_KEY（≥32字符），启动时会校验
    SECRET_KEY: str = Field(
        default="nexus-dev-secret-not-for-production", validation_alias="SECRET_KEY"
    )
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24小时
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # 开发环境 API Key 回退（仅非 production 环境生效）
    # 设置此值后，X-API-Key header 匹配时直接通过认证，不查数据库
    # 生产环境必须留空，否则启动安全校验会报错
    DEV_API_KEY: Optional[str] = Field(
        default=None, validation_alias="DEV_API_KEY"
    )

    # 数据库（开发用SQLite，生产环境通过环境变量覆盖为PostgreSQL）
    DATABASE_URL: str = Field(
        default="sqlite+aiosqlite:///./nexus.db",
        validation_alias="DATABASE_URL",
    )
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 20

    # Redis
    REDIS_URL: str = Field(default="redis://localhost:6379/0", validation_alias="REDIS_URL")

    # ARQ Worker 配置
    ARQ_WORKER_CONCURRENCY: int = Field(default=10, validation_alias="ARQ_WORKER_CONCURRENCY")
    ARQ_JOB_TIMEOUT: int = Field(default=3600, validation_alias="ARQ_JOB_TIMEOUT")  # 1小时
    ARQ_MAX_RETRIES: int = Field(default=3, validation_alias="ARQ_MAX_RETRIES")
    ARQ_KEEP_RESULT: int = Field(default=3600, validation_alias="ARQ_KEEP_RESULT")  # 结果保留1小时

    # ------------------------------------------------------------------
    # LLM网关 (LiteLLM Proxy)
    # ------------------------------------------------------------------
    LITELLM_PROXY_URL: str = Field(
        default="http://localhost:4000",
        validation_alias="LITELLM_PROXY_URL",
    )
    LITELLM_API_KEY: Optional[str] = Field(default=None, validation_alias="LITELLM_API_KEY")

    # LLM调用配置
    DEFAULT_LLM_TIMEOUT: float = Field(default=120.0, validation_alias="DEFAULT_LLM_TIMEOUT")
    DEFAULT_LLM_MAX_TOKENS: int = Field(default=4000, validation_alias="DEFAULT_LLM_MAX_TOKENS")
    DEFAULT_LLM_TEMPERATURE: float = Field(
        default=0.7, validation_alias="DEFAULT_LLM_TEMPERATURE"
    )

    # LLM模型配置（支持多模型Fallback）
    DEFAULT_LLM_MODEL: str = Field(default="deepseek-chat", validation_alias="DEFAULT_LLM_MODEL")
    DEFAULT_LLM_PROVIDER: str = Field(default="deepseek", validation_alias="DEFAULT_LLM_PROVIDER")

    # Provider 直连配置（当环境变量中有对应 API Key 时使用直连，否则走 LiteLLM Proxy）
    # 格式: {provider: (base_url, env_key_for_api_key)}
    PROVIDER_CONFIGS: dict[str, tuple[str, str]] = {
        "deepseek": ("https://api.deepseek.com/v1", "DEEPSEEK_API_KEY"),
        "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY"),
        "siliconflow": ("https://api.siliconflow.cn/v1", "SILICONFLOW_API_KEY"),
        "dashscope": ("https://dashscope.aliyuncs.com/compatible-mode/v1", "DASHSCOPE_API_KEY"),
        "zhipu": ("https://open.bigmodel.cn/api/paas/v4", "ZHIPU_API_KEY"),
    }

    # Fallback链：主模型 -> 备用模型列表
    # 示例: "gpt-4o,claude-sonnet-4,deepseek-chat"
    LLM_FALLBACK_CHAIN: list[str] = Field(default_factory=list)

    # LLM重试配置
    LLM_MAX_RETRIES: int = Field(default=3, validation_alias="LLM_MAX_RETRIES")
    LLM_RETRY_BASE_DELAY: float = Field(default=1.0, validation_alias="LLM_RETRY_BASE_DELAY")
    LLM_RETRY_MAX_DELAY: float = Field(default=60.0, validation_alias="LLM_RETRY_MAX_DELAY")
    LLM_RETRY_BACKOFF_MULTIPLIER: float = Field(
        default=2.0, validation_alias="LLM_RETRY_BACKOFF_MULTIPLIER"
    )

    # LLM并发控制
    LLM_MAX_CONCURRENT_CALLS: int = Field(
        default=10, validation_alias="LLM_MAX_CONCURRENT_CALLS"
    )

    # ------------------------------------------------------------------
    # Agent配置
    # ------------------------------------------------------------------
    DEFAULT_MAX_ITERATIONS: int = 10
    AGENT_MEMORY_ENABLED: bool = Field(default=True, validation_alias="AGENT_MEMORY_ENABLED")
    AGENT_MEMORY_BACKEND: str = Field(
        default="memory", validation_alias="AGENT_MEMORY_BACKEND"
    )  # memory / redis
    AGENT_MEMORY_MAX_TOKENS: int = Field(
        default=8000, validation_alias="AGENT_MEMORY_MAX_TOKENS"
    )

    # ------------------------------------------------------------------
    # 存储
    # ------------------------------------------------------------------
    S3_ENDPOINT: str = Field(default="http://localhost:9000", validation_alias="S3_ENDPOINT")
    S3_ACCESS_KEY: str = Field(default="nexus", validation_alias="S3_ACCESS_KEY")
    S3_SECRET_KEY: str = Field(default="nexus-secret-key", validation_alias="S3_SECRET_KEY")
    S3_BUCKET: str = Field(default="nexus-artifacts", validation_alias="S3_BUCKET")

    # ------------------------------------------------------------------
    # 引擎配置
    # ------------------------------------------------------------------
    MAX_WORKFLOW_STEPS: int = 500
    WORKFLOW_TIMEOUT_SECONDS: int = 3600
    DEFAULT_CHECKPOINT_INTERVAL: int = 1  # 每步都checkpoint

    # ------------------------------------------------------------------
    # HITL配置
    # ------------------------------------------------------------------
    DEFAULT_HITL_TIMEOUT_SECONDS: int = 86400  # 24小时
    HITL_NOTIFICATION_CHANNELS: list[str] = ["websocket", "email"]

    # ------------------------------------------------------------------
    # 审计
    # ------------------------------------------------------------------
    AUDIT_LOG_RETENTION_DAYS: int = 90

    # ------------------------------------------------------------------
    # RAG / Smart Cache 集成
    # ------------------------------------------------------------------
    SMART_CACHE_URL: str = Field(
        default="http://localhost:8777", validation_alias="SMART_CACHE_URL"
    )
    SMART_CACHE_API_KEY: Optional[str] = Field(
        default=None, validation_alias="SMART_CACHE_API_KEY"
    )
    SMART_CACHE_TIMEOUT: float = Field(default=30.0, validation_alias="SMART_CACHE_TIMEOUT")
    SMART_CACHE_PROJECT_ID: str = Field(
        default="nexus-default", validation_alias="SMART_CACHE_PROJECT_ID"
    )

    # ------------------------------------------------------------------
    # MCP (Model Context Protocol)
    # ------------------------------------------------------------------
    MCP_SERVER_ENABLED: bool = Field(default=False, validation_alias="MCP_SERVER_ENABLED")
    MCP_SERVER_PORT: int = Field(default=8766, validation_alias="MCP_SERVER_PORT")
    MCP_SERVER_HOST: str = Field(default="0.0.0.0", validation_alias="MCP_SERVER_HOST")

    # ------------------------------------------------------------------
    # 可观测性
    # ------------------------------------------------------------------
    ENABLE_PROMETHEUS: bool = True
    ENABLE_OPENTELEMETRY: bool = False
    LOG_LEVEL: str = Field(default="INFO", validation_alias="LOG_LEVEL")


# 全局配置实例
settings = Settings()
