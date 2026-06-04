# P11c — 生态建设冲刺：工具市场 + 行业模板 + SDK/CLI

> 面向 AI 代理的工作者：使用 superpowers:subagent-driven-development 逐任务实现。

**目标：** 在 2 个月内构建 NEXUS 的工具生态和行业解决方案，降低用户上手门槛，提升商业价值。

**前提：** P11a+P11b 已完成（测试覆盖率 ≥60%，核心能力深化完成）

---

## 工作包总览

| 工作包 | 时间 | 目标 |
|--------|------|------|
| C1 预置工具连接器 | Week 1-2 | 5-10 个开箱即用的工具 |
| C2 行业Agent模板 | Week 2-4 | 3-6 个行业解决方案模板 |
| C3 CLI 增强 | Week 4-6 | 完善的命令行开发工具 |
| C4 工具市场 UI | Week 6-8 | 前端工具浏览/安装/配置界面 |

---

## C1: 预置工具连接器

**目标：** 提供可直接使用的企业常用工具

**工具清单：**
1. `nexus/tools/connectors/email_tool.py` — 邮件发送（SMTP）
2. `nexus/tools/connectors/webhook_tool.py` — 通用 Webhook 调用
3. `nexus/tools/connectors/file_tool.py` — 文件读写/处理
4. `nexus/tools/connectors/http_tool.py` — 通用 HTTP 请求
5. `nexus/tools/connectors/json_tool.py` — JSON 数据转换/查询

**验收标准：**
- [ ] 5 个预置工具全部可用
- [ ] 每个工具有独立测试
- [ ] 工具可被 Agent 直接调用

---

## C2: 行业Agent模板

**目标：** 提供开箱即用的行业方案

**模板清单：**
1. `nexus/templates/code_reviewer_v2.json` — 增强版代码审查 Agent
2. `nexus/templates/data_analyst.json` — 数据分析报告 Agent
3. `nexus/templates/customer_service.json` — 客服自动化 Agent

**验收标准：**
- [ ] 3 个模板定义文件
- [ ] 每个模板包含 Agent + Workflow 配置
- [ ] 模板可直接导入使用

---

## C3: CLI 增强

**目标：** 完善 `nexus_cli.py` 为全功能 CLI 工具

**命令清单：**
- `nexus template list` — 列出可用模板
- `nexus template install <name>` — 安装模板
- `nexus tool list` — 列出可用工具
- `nexus tool test <name>` — 测试工具

**验收标准：**
- [ ] 4 个新命令可用
- [ ] 测试覆盖

---
