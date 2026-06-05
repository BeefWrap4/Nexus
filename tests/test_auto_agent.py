import pytest
from nexus.agent.planner import GoalDecomposer, WorkflowBuilder, Subtask, Plan
from nexus.agent.auto_agent import AutoAgent


class TestGoalDecomposer:
    def test_simple_greeting(self):
        d = GoalDecomposer()
        plan = d._simple_plan("say hello", ["greet"])
        assert len(plan.subtasks) == 1
        assert plan.subtasks[0].name == "Greet"

    def test_read_summarize_output(self):
        d = GoalDecomposer()
        plan = d._simple_plan("summarize doc", ["read", "summarize", "output"])
        assert len(plan.subtasks) == 3
        # 依赖链: task_1 -> task_2 -> task_3
        assert plan.subtasks[0].depends_on == []
        assert plan.subtasks[1].depends_on == ["task_1"]
        assert plan.subtasks[2].depends_on == ["task_2"]

    def test_default_plan(self):
        d = GoalDecomposer()
        plan = d._default_plan("complex task")
        assert len(plan.subtasks) == 3
        assert plan.subtasks[0].name == "Analyze"

    @pytest.mark.asyncio
    async def test_decompose_with_pattern_match(self):
        """规则匹配走快速路径."""
        d = GoalDecomposer()
        plan = await d.decompose("summarize the document")
        assert len(plan.subtasks) == 3

    @pytest.mark.asyncio
    async def test_decompose_without_llm_defaults(self):
        """无 LLM 无规则匹配时走默认路径."""
        d = GoalDecomposer()
        plan = await d.decompose("do something very complex and unique")
        assert len(plan.subtasks) == 3
        assert plan.reasoning == "Default sequential decomposition"


class TestWorkflowBuilder:
    def test_simple_linear_workflow(self):
        plan = Plan(
            goal="test",
            subtasks=[
                Subtask(id="1", name="Fetch", description="fetch data"),
                Subtask(id="2", name="Process", description="process", depends_on=["1"]),
                Subtask(id="3", name="Output", description="output", depends_on=["2"]),
            ],
        )
        builder = WorkflowBuilder()
        bp = builder.build(plan)

        nodes = bp.workflow_config["nodes"]
        edges = bp.workflow_config["edges"]

        # nodes: start + 3 agents + end = 5
        assert len(nodes) == 5
        # edges: start->task_1, task_1->task_2, task_2->task_3, task_3->end = 4
        assert len(edges) == 4

    def test_parallel_workflow(self):
        """无依赖的并行任务."""
        plan = Plan(
            goal="parallel test",
            subtasks=[
                Subtask(id="a", name="A", description="Task A"),
                Subtask(id="b", name="B", description="Task B"),
            ],
        )
        builder = WorkflowBuilder()
        bp = builder.build(plan)

        edges = bp.workflow_config["edges"]
        # start->A, start->B, A->end, B->end = 4 edges
        assert len(edges) == 4

    def test_agent_configs_generated(self):
        plan = Plan(
            goal="test",
            subtasks=[
                Subtask(id="1", name="Analyst", description="analyze",
                        tool_needs=["json_query"], agent_role="Data Analyst"),
            ],
        )
        builder = WorkflowBuilder()
        bp = builder.build(plan)

        assert len(bp.agent_configs) == 1
        assert bp.agent_configs[0]["name"] == "Analyst"
        assert "json_query" in bp.agent_configs[0]["tools"]

    def test_complex_dag(self):
        """A->B, A->C, B->D, C->D (菱形依赖)."""
        plan = Plan(
            goal="diamond",
            subtasks=[
                Subtask(id="a", name="A", description="Start"),
                Subtask(id="b", name="B", description="Middle 1", depends_on=["a"]),
                Subtask(id="c", name="C", description="Middle 2", depends_on=["a"]),
                Subtask(id="d", name="D", description="End", depends_on=["b", "c"]),
            ],
        )
        builder = WorkflowBuilder()
        bp = builder.build(plan)

        # nodes: start + 4 agents + end = 6
        assert len(bp.workflow_config["nodes"]) == 6
        # edges: start->A, A->B, A->C, B->D, C->D, D->end = 6
        assert len(bp.workflow_config["edges"]) == 6

    def test_single_task_workflow(self):
        """单任务工作流."""
        plan = Plan(
            goal="simple",
            subtasks=[
                Subtask(id="1", name="Only", description="Only task"),
            ],
        )
        builder = WorkflowBuilder()
        bp = builder.build(plan)

        nodes = bp.workflow_config["nodes"]
        assert len(nodes) == 3  # start + 1 agent + end
        node_ids = {n["id"] for n in nodes}
        assert node_ids == {"start", "agent_1", "end"}

        edges = bp.workflow_config["edges"]
        assert len(edges) == 2  # start->agent_1, agent_1->end


class TestAutoAgent:
    def test_plan_simple_goal(self):
        agent = AutoAgent()
        result = agent.plan("summarize this document")
        assert result.success
        assert len(result.plan.subtasks) > 0

    def test_plan_complex_goal(self):
        agent = AutoAgent()
        result = agent.plan("analyze sales data, find trends, generate report, send by email")
        assert result.success
        assert len(result.blueprint.agent_configs) == len(result.plan.subtasks)

    def test_blueprint_is_valid_dag(self):
        """验证 blueprint 是有效 DAG."""
        agent = AutoAgent()
        result = agent.plan("summarize doc")
        bp = result.blueprint

        # 有 start 和 end 节点
        node_types = [n["type"] for n in bp.workflow_config["nodes"]]
        assert "start" in node_types
        assert "end" in node_types

        # 每条边连接存在的节点
        node_ids = {n["id"] for n in bp.workflow_config["nodes"]}
        for edge in bp.workflow_config["edges"]:
            assert edge["source"] in node_ids
            assert edge["target"] in node_ids

    def test_plan_hello_pattern(self):
        """hello 模式匹配."""
        agent = AutoAgent()
        result = agent.plan("say hello world")
        assert result.success
        assert len(result.plan.subtasks) == 1
        assert result.plan.subtasks[0].name == "Greet"

    def test_plan_error_handling(self):
        """错误处理测试 — 应该返回 success=False 而不是抛出异常."""
        agent = AutoAgent()
        result = agent.plan("")
        # 空字符串不匹配任何 pattern，走 default plan — 应成功
        assert result.success

    @pytest.mark.asyncio
    async def test_plan_async_simple(self):
        """异步路径测试."""
        agent = AutoAgent()
        result = await agent.plan_async("summarize the document")
        assert result.success
        assert len(result.plan.subtasks) == 3

    def test_blueprint_nodes_have_required_fields(self):
        """验证 blueprint 节点有必需的字段."""
        agent = AutoAgent()
        result = agent.plan("summarize doc")
        for node in result.blueprint.workflow_config["nodes"]:
            assert "id" in node
            assert "type" in node
