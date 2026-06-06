# =============================================================================
# NEXUS UI - Multi-stage Docker Build
# Stage 1: Build Vue 3 app with Vite
# Stage 2: Serve with nginx
# =============================================================================

# ---------------------------------------------------------------------------
# Stage 1: Build
# ---------------------------------------------------------------------------
FROM node:20-alpine AS builder

WORKDIR /app

# 国内源加速 — 可通过 build-arg 关闭
ARG USE_CN_MIRROR=true
RUN if [ "$USE_CN_MIRROR" = "true" ]; then \
        npm config set registry https://registry.npmmirror.com; \
    fi

# Install dependencies (leveraging Docker cache)
COPY package.json package-lock.json ./
RUN npm ci

# Copy source and build
COPY . .
RUN npm run build

# ---------------------------------------------------------------------------
# Stage 2: Production Serve
# ---------------------------------------------------------------------------
FROM nginx:alpine

# 国内源加速（Alpine apk）— 可通过 build-arg 关闭
ARG USE_CN_MIRROR=true
RUN if [ "$USE_CN_MIRROR" = "true" ]; then \
        sed -i 's|dl-cdn.alpinelinux.org|mirrors.aliyun.com|g' /etc/apk/repositories; \
    fi

# Copy built static files
COPY --from=builder /app/dist /usr/share/nginx/html

# Copy nginx configuration
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -qO- http://127.0.0.1:80/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
