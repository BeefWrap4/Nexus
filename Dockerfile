# =============================================================================
# NEXUS - Enterprise Multi-Agent Orchestration Engine
# Multi-stage Docker Build
# =============================================================================

# ---------------------------------------------------------------------------
# Stage 1: Builder
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS builder

WORKDIR /build

# 国内源加速（阿里云）— 可通过 build-arg 关闭
ARG USE_CN_MIRROR=true
RUN if [ "$USE_CN_MIRROR" = "true" ]; then \
        sed -i 's|http://deb.debian.org|https://mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources \
        && sed -i 's|http://security.debian.org|https://mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources; \
    fi

# 安装构建依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# 配置 pip 国内源
RUN if [ "$USE_CN_MIRROR" = "true" ]; then \
        pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/ \
        && pip config set global.trusted-host mirrors.aliyun.com; \
    fi

# 复制依赖文件
COPY requirements.txt .

# 创建虚拟环境并安装Python依赖
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# ---------------------------------------------------------------------------
# Stage 2: Production
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS production

WORKDIR /app

# 国内源加速（阿里云）— 从 builder stage 继承 build-arg 需重新声明
ARG USE_CN_MIRROR=true
RUN if [ "$USE_CN_MIRROR" = "true" ]; then \
        sed -i 's|http://deb.debian.org|https://mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources \
        && sed -i 's|http://security.debian.org|https://mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources; \
    fi

# 安装运行时系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql-client \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 从builder复制虚拟环境
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# 创建非root用户
RUN groupadd -r nexus && useradd -r -g nexus nexus

# 创建必要的目录
RUN mkdir -p /app/logs /app/data && chown -R nexus:nexus /app

# 复制应用代码
COPY --chown=nexus:nexus nexus/ ./nexus/
COPY --chown=nexus:nexus alembic.ini .
COPY --chown=nexus:nexus nexus_cli.py .

# 切换到非root用户
USER nexus

# 暴露端口
EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# 启动命令
CMD ["uvicorn", "nexus.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ---------------------------------------------------------------------------
# Stage 3: Development
# ---------------------------------------------------------------------------
FROM production AS development

USER root

# 国内源已在 production stage 配置，此处直接复用
# 安装开发额外依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    vim \
    && rm -rf /var/lib/apt/lists/*

# 安装开发/测试依赖
RUN pip install --no-cache-dir \
    pytest>=8.0.0 \
    pytest-asyncio>=0.23.0 \
    pytest-cov>=4.1.0 \
    black>=24.0.0 \
    ruff>=0.3.0 \
    mypy>=1.8.0 \
    httpx>=0.27.0

# 复制测试代码
COPY --chown=nexus:nexus tests/ ./tests/
COPY --chown=nexus:nexus pytest.ini .

USER nexus

# 开发模式启动（带热重载）
CMD ["uvicorn", "nexus.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
