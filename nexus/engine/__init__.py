"""NEXUS核心编排引擎.

基于WAT engine/ 升级:
- PhaseController (线性状态机) → WorkflowEngine (DAG图执行)
- GameEngine (游戏专用) → 通用工作流编排
- InfoIsolation → PermissionEngine (RBAC)
- CheckpointManager → 增强版(支持fork/回溯)
"""