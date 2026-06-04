# NEXUS 监控告警配置文档

## 📋 目录

- [概述](#概述)
- [架构设计](#架构设计)
- [自定义指标](#自定义指标)
- [告警规则](#告警规则)
- [钉钉通知集成](#钉钉通知集成)
- [部署指南](#部署指南)
- [Grafana仪表板](#grafana仪表板)
- [故障排查](#故障排查)

---

## 概述

NEXUS监控告警系统基于Prometheus生态构建,提供以下核心功能:

✅ **自定义指标采集**: 工作流、Agent、队列三大维度的详细指标  
✅ **智能告警规则**: 7+条关键业务告警规则  
✅ **多渠道通知**: 钉钉Webhook实时推送告警  
✅ **可视化监控**: Grafana性能仪表板  

### 技术栈

| 组件 | 版本 | 用途 |
|------|------|------|
| Prometheus | latest | 指标收集和存储 |
| Alertmanager | latest | 告警路由和通知 |
| Grafana | latest | 数据可视化 |
| DingTalk Webhook | latest | 钉钉通知适配器 |

---

## 架构设计

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
│   Nexus API  │     │ Nexus Worker │     │  LLM Tracer     │
│  (FastAPI)   │     │   (ARQ)      │     │                 │
└──────┬──────┘     └──────┬───────┘     └────────┬────────┘
       │                   │                       │
       │ /metrics          │ /metrics              │
       ▼                   ▼                       ▼
┌─────────────────────────────────────────────────────────┐
│                  Prometheus Server                       │
│  - Scrape Interval: 15s                                  │
│  - Evaluation Interval: 15s                              │
│  - Rule Files: monitoring/alerts/*.yml                   │
└──────────────────────┬──────────────────────────────────┘
                       │
                       │ Alert Rules Triggered
                       ▼
┌─────────────────────────────────────────────────────────┐
│                  Alertmanager                            │
│  - Group By: alertname, severity, team                  │
│  - Routing: Critical/Database/Finance/Infra             │
│  - Inhibition: Critical suppresses Warning              │
└──────────────────────┬──────────────────────────────────┘
                       │
                       │ Webhook Notification
                       ▼
┌─────────────────────────────────────────────────────────┐
│              DingTalk Webhook Adapter                    │
│  - Converts Prometheus alerts to DingTalk cards         │
│  - Supports multiple webhook URLs per team              │
└──────────────────────┬──────────────────────────────────┘
                       │
                       │ HTTP POST
                       ▼
┌─────────────────────────────────────────────────────────┐
│                 DingTalk Groups                          │
│  - Default Team                                          │
│  - Database Team                                         │
│  - Finance Team                                          │
│  - Infrastructure Team                                   │
└─────────────────────────────────────────────────────────┘
```

---

## 自定义指标

### 1. 工作流执行指标 (`nexus/observability/workflow_metrics.py`)

| 指标名称 | 类型 | 标签 | 说明 |
|---------|------|------|------|
| `nexus_workflow_duration_seconds` | Histogram | tenant_id, workflow_name, status | 工作流执行延迟 |
| `nexus_workflow_runs_total` | Counter | tenant_id, status | 工作流执行总数 |
| `nexus_workflow_running` | Gauge | tenant_id | 当前运行中的工作流数 |
| `nexus_node_duration_seconds` | Histogram | node_type, status | 节点执行延迟 |
| `nexus_node_executions_total` | Counter | node_type, status | 节点执行总数 |
| `nexus_workflow_failures_total` | Counter | tenant_id, error_type | 工作流失败次数 |
| `nexus_node_failures_total` | Counter | node_type, error_type | 节点失败次数 |

**使用示例:**

```python
from nexus.observability.workflow_metrics import record_workflow_execution

record_workflow_execution(
    tenant_id="tenant-123",
    workflow_name="customer-support",
    status="succeeded",
    duration_seconds=2.5
)
```

### 2. Agent系统指标 (`nexus/observability/agent_metrics.py`)

| 指标名称 | 类型 | 标签 | 说明 |
|---------|------|------|------|
| `nexus_agent_decision_latency_seconds` | Histogram | agent_name, status | Agent决策延迟 |
| `nexus_agent_executions_total` | Counter | agent_name, status | Agent执行总数 |
| `nexus_llm_calls_total` | Counter | provider, model, status | LLM调用总数 |
| `nexus_llm_cost_usd` | Counter | provider, model | LLM调用成本(USD) |
| `nexus_llm_tokens_total` | Counter | type (input/output/total) | Token使用量 |
| `nexus_llm_call_latency_seconds` | Histogram | provider, model | LLM调用延迟 |
| `nexus_llm_call_failures_total` | Counter | provider, model, error_type | LLM调用失败次数 |
| `nexus_llm_retries_total` | Counter | provider, model | LLM重试次数 |

**使用示例:**

```python
from nexus.observability.agent_metrics import record_llm_call

record_llm_call(
    provider="openai",
    model="gpt-4o",
    status="success",
    prompt_tokens=150,
    completion_tokens=300,
    cost_usd=0.015,
    latency_seconds=1.2
)
```

### 3. 队列指标 (`nexus/observability/queue_metrics.py`)

| 指标名称 | 类型 | 标签 | 说明 |
|---------|------|------|------|
| `nexus_arq_queue_length` | Gauge | - | ARQ队列长度 |
| `nexus_arq_active_workers` | Gauge | - | 活跃Worker数量 |
| `nexus_task_processing_time_seconds` | Histogram | job_type | 任务处理时间 |
| `nexus_task_executions_total` | Counter | job_type, status | 任务执行总数 |
| `nexus_task_failures_total` | Counter | job_type, error_type | 任务失败次数 |
| `nexus_task_retries_total` | Counter | job_type | 任务重试次数 |
| `nexus_dead_letter_jobs` | Gauge | - | 死信队列任务数 |

**使用示例:**

```python
from nexus.observability.queue_metrics import update_queue_length

update_queue_length(length=42)
```

---

## 告警规则

所有告警规则定义在 `monitoring/alerts/nexus_alerts.yml`。

### 1. HighAPIErrorRate (Critical)

- **触发条件**: API 5xx错误率 > 5% (持续5分钟)
- **严重程度**: critical
- **负责团队**: backend
- **影响**: 用户请求大量失败
- **排查步骤**:
  1. 检查应用日志: `docker logs nexus-api`
  2. 检查依赖服务状态 (PostgreSQL, Redis, LiteLLM)
  3. 查看最近的代码部署

### 2. HighP95Latency (Warning)

- **触发条件**: API P95延迟 > 2s (持续5分钟)
- **严重程度**: warning
- **负责团队**: backend
- **影响**: 用户体验下降
- **排查步骤**:
  1. 检查慢查询日志
  2. 分析LLM调用延迟
  3. 检查网络状况

### 3. DatabaseConnectionPoolExhausted (Critical)

- **触发条件**: PostgreSQL连接池使用率 > 90% (持续2分钟)
- **严重程度**: critical
- **负责团队**: database
- **影响**: 新请求无法获取数据库连接
- **排查步骤**:
  1. 检查长事务: `SELECT * FROM pg_stat_activity WHERE state = 'active' AND duration > interval '5 minutes';`
  2. 检查连接泄漏
  3. 考虑增加连接池大小

### 4. HighWorkflowFailureRate (Warning)

- **触发条件**: 工作流失败率 > 10% (持续10分钟)
- **严重程度**: warning
- **负责团队**: platform
- **影响**: 业务流程中断
- **排查步骤**:
  1. 检查工作流定义是否有效
  2. 检查节点执行器注册情况
  3. 查看失败工作流的错误日志

### 5. HighLLMCost (Warning)

- **触发条件**: LLM每小时成本 > $10 (持续15分钟)
- **严重程度**: warning
- **负责团队**: finance
- **影响**: 运营成本超支
- **排查步骤**:
  1. 检查是否有异常调用模式
  2. 优化提示词减少Token使用
  3. 考虑切换到更经济的模型

### 6. QueueBacklog (Warning)

- **触发条件**: ARQ队列长度 > 100 (持续5分钟)
- **严重程度**: warning
- **负责团队**: platform
- **影响**: 任务处理延迟
- **排查步骤**:
  1. 检查Worker健康状况: `docker logs nexus-worker`
  2. 增加Worker实例数量
  3. 检查是否有阻塞任务

### 7. HighDiskUsage (Warning)

- **触发条件**: 根分区磁盘使用率 > 80% (持续10分钟)
- **严重程度**: warning
- **负责团队**: infrastructure
- **影响**: 可能导致服务崩溃
- **排查步骤**:
  1. 清理日志文件: `journalctl --vacuum-size=100M`
  2. 清理Docker镜像: `docker system prune -a`
  3. 扩展磁盘空间

---

## 钉钉通知集成

### 配置步骤

#### 1. 创建钉钉机器人

1. 打开钉钉群聊
2. 点击右上角"设置" → "智能群助手" → "添加机器人"
3. 选择"自定义"机器人
4. 安全设置选择"自定义关键词"(推荐):
   - 关键词1: `[CRITICAL]`
   - 关键词2: `[WARNING]`
   - 关键词3: `Nexus`
5. 复制Webhook URL中的 `access_token`

#### 2. 配置环境变量

编辑 `.env` 文件:

```bash
# 钉钉机器人Webhook URL
DINGTALK_WEBHOOK_URL_1=https://oapi.dingtalk.com/robot/send?access_token=YOUR_TOKEN_1
DINGTALK_WEBHOOK_URL_2=https://oapi.dingtalk.com/robot/send?access_token=YOUR_TOKEN_2
DINGTALK_WEBHOOK_URL_3=https://oapi.dingtalk.com/robot/send?access_token=YOUR_TOKEN_3
DINGTALK_WEBHOOK_URL_4=https://oapi.dingtalk.com/robot/send?access_token=YOUR_TOKEN_4
```

**建议分配:**
- URL_1: 默认团队 + Critical告警
- URL_2: Database团队
- URL_3: Finance团队
- URL_4: Infrastructure团队

#### 3. 启动服务

```bash
# 启动监控栈
docker compose --profile monitoring up -d

# 验证服务状态
docker compose ps | grep -E "(prometheus|alertmanager|dingtalk)"
```

### 告警消息格式

钉钉会收到如下格式的卡片消息:

```
🚨 [CRITICAL] Nexus API 错误率过高

API 5xx 错误率达到 8.5%，超过阈值 5%。
请立即检查应用日志和依赖服务状态。

触发时间: 2026-06-04 15:30:00
持续时间: 5m
严重级别: critical
负责团队: backend

[查看详情] [运行手册]
```

---

## 部署指南

### 前置要求

- Docker Compose v2.0+
- 至少4GB可用内存
- 至少10GB可用磁盘空间

### 快速启动

```bash
# 1. 进入项目目录
cd d:\AI_learning\nexus

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env 文件，设置钉钉Webhook URL

# 3. 启动监控栈
docker compose --profile monitoring up -d

# 4. 验证服务
curl http://localhost:9090/-/ready    # Prometheus
curl http://localhost:9093/-/ready    # Alertmanager
curl http://localhost:3000/api/health # Grafana
```

### 访问地址

| 服务 | 地址 | 默认凭证 |
|------|------|----------|
| Prometheus | http://localhost:9090 | 无需认证 |
| Alertmanager | http://localhost:9093 | 无需认证 |
| Grafana | http://localhost:3000 | admin/admin |

### 导入Grafana仪表板

1. 访问 http://localhost:3000
2. 登录 (admin/admin)
3. 左侧菜单 → Dashboards → Import
4. 上传 `monitoring/grafana/dashboards/nexus-performance.json`
5. 选择数据源: Prometheus
6. 点击 Import

---

## Grafana仪表板

### 面板说明

`monitoring/grafana/dashboards/nexus-performance.json` 包含12个面板:

1. **API请求量和延迟趋势**: 实时监控API流量和响应时间
2. **API P95/P99延迟**: 百分位延迟分析
3. **工作流执行成功率**: 整体成功率统计
4. **当前运行中的工作流数**: 并发工作流监控
5. **工作流执行延迟分布**: 热力图展示延迟分布
6. **LLM调用成本和Token使用**: 成本追踪
7. **LLM Token使用量**: Input/Output Token速率
8. **数据库连接池使用率**: 连接池健康度
9. **ARQ队列长度**: 队列积压监控
10. **任务处理时间分布**: 直方图展示
11. **SLO达标率**: API <2s 的合规率
12. **活跃Worker数量**: Worker健康度

### 自定义仪表板

如需添加自定义面板:

1. 在Grafana中点击 "Add panel"
2. 选择可视化类型 (Graph, Stat, Gauge等)
3. 编写PromQL查询
4. 保存仪表板

**常用PromQL示例:**

```promql
# 工作流平均执行时间
avg(rate(nexus_workflow_duration_seconds_sum[5m]) / rate(nexus_workflow_duration_seconds_count[5m]))

# LLM调用成功率
sum(rate(nexus_llm_calls_total{status="success"}[5m])) / sum(rate(nexus_llm_calls_total[5m])) * 100

# 队列处理速率
rate(nexus_task_executions_total{status="success"}[5m])
```

---

## 故障排查

### Prometheus未采集到指标

**症状**: Prometheus targets页面显示down

**排查步骤**:

```bash
# 1. 检查服务是否运行
docker compose ps

# 2. 检查/metrics端点
curl http://localhost:8765/metrics
curl http://localhost:8080/metrics

# 3. 检查Prometheus日志
docker logs nexus-prometheus

# 4. 验证配置文件
docker exec nexus-prometheus promtool check config /etc/prometheus/prometheus.yml
```

### 告警未触发

**症状**: 指标异常但Alertmanager未发送通知

**排查步骤**:

```bash
# 1. 检查告警规则是否加载
curl http://localhost:9090/api/v1/rules

# 2. 检查Alertmanager配置
curl http://localhost:9093/api/v2/status

# 3. 手动触发测试告警
curl -X POST http://localhost:9093/api/v1/alerts \
  -H "Content-Type: application/json" \
  -d '[{
    "labels": {
      "alertname": "TestAlert",
      "severity": "warning"
    },
    "annotations": {
      "summary": "测试告警"
    }
  }]'

# 4. 检查Alertmanager日志
docker logs nexus-alertmanager
```

### 钉钉通知未收到

**症状**: Alertmanager显示sent但钉钉无消息

**排查步骤**:

```bash
# 1. 检查dingtalk-webhook服务
docker logs nexus-dingtalk-webhook

# 2. 验证Webhook URL是否正确
curl -X POST "$DINGTALK_WEBHOOK_URL_1" \
  -H "Content-Type: application/json" \
  -d '{"msgtype":"text","text":{"content":"测试消息"}}'

# 3. 检查网络连接
docker exec nexus-alertmanager ping dingtalk-webhook

# 4. 检查Alertmanager接收器配置
curl http://localhost:9093/api/v2/receivers
```

### Grafana仪表板无数据

**症状**: 面板显示"No data"

**排查步骤**:

1. 确认Prometheus数据源配置正确
2. 检查时间范围是否合适 (尝试调整为"Last 1 hour")
3. 验证PromQL语法 (在Explore页面测试)
4. 检查指标是否已采集 (在Prometheus Graph页面查询)

---

## 维护指南

### 备份监控数据

```bash
# 备份Prometheus数据
docker run --rm -v nexus_prometheus-data:/data -v $(pwd):/backup alpine tar czf /backup/prometheus-backup.tar.gz -C /data .

# 备份Grafana配置
docker run --rm -v nexus_grafana-data:/data -v $(pwd):/backup alpine tar czf /backup/grafana-backup.tar.gz -C /data .
```

### 清理历史数据

```bash
# 删除7天前的Prometheus数据
docker exec nexus-prometheus rm -rf /prometheus/chunks/2026*

# 重启Prometheus以释放空间
docker compose restart prometheus
```

### 升级监控组件

```bash
# 拉取最新镜像
docker compose pull prometheus alertmanager grafana

# 滚动重启
docker compose up -d prometheus alertmanager grafana
```

---

## 参考资料

- [Prometheus官方文档](https://prometheus.io/docs/)
- [Alertmanager配置指南](https://prometheus.io/docs/alerting/latest/configuration/)
- [Grafana仪表板教程](https://grafana.com/docs/grafana/latest/dashboards/)
- [钉钉机器人开发文档](https://open.dingtalk.com/document/robots)
- [PromQL最佳实践](https://prometheus.io/docs/practices/querying/)

---

**最后更新**: 2026-06-04  
**维护者**: Nexus Platform Team
