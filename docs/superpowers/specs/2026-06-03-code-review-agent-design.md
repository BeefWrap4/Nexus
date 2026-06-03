# NEXUS Phase 8: 代码审查 Agent 应用

**日期:** 2026-06-03  
**目标:** 用 NEXUS 构建完整代码审查 Agent，验证平台核心能力并暴露缺口  
**策略:** 串行深挖，先交互式工作台（8.1），再 PR 自动审查机器人（8.2）

## 架构

```
Phase 8.1: 交互式审查工作台
nexus-ui → API → Workflow → Agent "code-reviewer" + Tools → EventBus → WebSocket → UI

Phase 8.2: PR 审查机器人
GitHub Webhook → API trigger → Workflow → Agent + Tools → GitHub API (post review)
```

## Agent 工具集

| 工具 | 类型 | 输入 | 输出 |
|------|------|------|------|
| `parse_diff` | PYTHON | diff 文本 | `[{file, hunks, lines}]` |
| `detect_language` | PYTHON | `[{file, content}]` | `[{file, language}]` |
| `security_check` | PYTHON | `{file, content, language}` | `[{severity, line, issue, suggestion}]` |
| `perf_check` | PYTHON | `{file, content, language}` | `[{severity, line, issue, suggestion}]` |
| `style_check` | PYTHON | `{file, content, language}` | `[{severity, line, issue, suggestion}]` |
| `code_analyze` | LLM | `{file, content, focus}` | `[{finding}]` |

设计原则: Python 工具做确定性检查（可审计），LLM 工具做语义分析。

## 审查标准 Prompt 模板

Jinja2 模板，变量: `role`, `language`, `focus_areas`, `strictness`, `diff_content`。通过 NEXUS Prompt 系统管理版本，支持 A/B 测试和 Eval。

## 前端设计

### 审查工作台 (CodeReview.vue)
- 左侧: 审查报告卡片（severity 色彩编码，可展开详情，追问按钮）
- 右侧: 原始代码 diff 视图
- 底部: 追问输入框 + 多轮对话
- 顶部: 输入区（粘贴 diff / 上传文件），审查标准选择，开始按钮

### PR Bot 配置 (PRBotConfig.vue)
- GitHub 仓库连接配置
- Webhook 注册
- 审查触发规则（自动 / 手动 / 定时）

## 实施计划

### Phase 8.1: 交互式审查工作台
1. **审查工具集** (`nexus/tools/code_review.py`) — 6 个 Tool 实现
2. **审查 Agent 配置** — PrompTemplate + AgentConfig
3. **审查工作流** — Workflow DAG (start → review → end)
4. **审查 API** — `/api/v1/reviews` (提交 review, 流式)
5. **前端审查工作台** — CodeReview.vue
6. **测试** — test_code_review.py

### Phase 8.2: PR 审查机器人
7. **GitHub Tool** (`nexus/tools/github.py`) — get_pr_diff, post_review_comment
8. **GitHub Webhook 路由** — `/api/v1/triggers/github`
9. **PR Bot 工作流** — 自动化工作流模板
10. **前端配置页** — PRBotConfig.vue
11. **测试** — test_github_bot.py

## 复用现有模块

- WorkflowEngine + EventBus + WebSocket (Phase 1-3)
- Agent BaseAgent + ToolRegistry (Phase 4)
- PromptTemplate + PromptEngine (Phase 6.2)
- LLM Trace (Phase 6.1)
- RunMonitor.vue 流式展示组件 (Phase 3)

## 验证标准

1. 粘贴一段包含 SQL 注入 + N+1 查询的代码 → Agent 检出并给修复建议
2. 流式审查过程通过 WebSocket 实时展示
3. 追问功能: Agent 多轮对话给出具体修改方案
4. PR Bot: 模拟 GitHub webhook → 自动提交 review comment
5. 178 现有测试 + 新增测试全部通过
