# NEXUS 端到端示例

## 前置条件

```bash
# 确保已配置 DeepSeek API Key
cp .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY=sk-xxx

# 安装依赖
pip install -r requirements.txt
```

## 示例列表

### 1. contract_review.py — 合同审查流程

**5节点工作流**：条款提取 → 风险评估 → 人工审批(HITL) → 汇总输出

```bash
python examples/contract_review.py
```

**展示能力**：
- 多Agent串行协作
- Human-in-the-Loop审批节点
- 10秒超时自动通过（演示模式）

---

### 2. invoice_processor.py — 发票智能处理

**3节点Agent链**：提取发票信息 → 合规性校验 → 汇总输出

```bash
python examples/invoice_processor.py
```

**展示能力**：
- 非结构化文本→结构化数据提取
- 多维度合规校验
- 纯LLM驱动工作流（无人工交互）

---

## 自定义示例

基于以上模板创建自己的工作流：

1. 用 `Node()` 定义节点（Agent / HITL / Condition 等）
2. 用 `Edge()` 定义节点间连线
3. 用 `WorkflowEngine` 执行

Agent节点的核心配置：
```python
Node(id="my_agent", type=NodeType.AGENT, config={
    "agent_name": "角色名称",      # 必填
    "agent_role": "角色描述",      # 影响LLM行为
    "task_description": "任务描述", # Agent收到的任务指令
    "provider": "deepseek",        # LLM Provider
    "model": "deepseek-chat",     # 模型名
}, depends_on=["前置节点ID"]),     # 执行依赖
```
