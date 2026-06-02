<template>
  <div class="node-panel">
    <h4 class="panel-title">
      <AppstoreOutlined /> 节点库
    </h4>
    <div class="node-list">
      <div
        v-for="node in nodeTypes"
        :key="node.type"
        class="node-item"
        :class="`node-type-${node.type}`"
        draggable="true"
        @dragstart="onDragStart($event, node)"
      >
        <component :is="node.icon" class="node-icon" />
        <div class="node-info">
          <div class="node-name">{{ node.label }}</div>
          <div class="node-desc">{{ node.description }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import {
  PlayCircleOutlined,
  RobotOutlined,
  ToolOutlined,
  QuestionCircleOutlined,
  ForkOutlined,
  PauseCircleOutlined,
  ClockCircleOutlined,
  CheckCircleOutlined,
  AppstoreOutlined,
} from '@ant-design/icons-vue'
import type { Component } from 'vue'

export interface NodeTypeItem {
  type: string
  label: string
  description: string
  icon: Component
}

const nodeTypes: NodeTypeItem[] = [
  {
    type: 'start',
    label: '开始',
    description: '工作流入口节点',
    icon: PlayCircleOutlined,
  },
  {
    type: 'agent',
    label: 'Agent',
    description: 'AI 智能体执行',
    icon: RobotOutlined,
  },
  {
    type: 'tool',
    label: '工具',
    description: '调用外部工具',
    icon: ToolOutlined,
  },
  {
    type: 'hitl',
    label: '人工审核',
    description: '等待人工确认',
    icon: PauseCircleOutlined,
  },
  {
    type: 'condition',
    label: '条件分支',
    description: 'IF/ELSE 判断',
    icon: QuestionCircleOutlined,
  },
  {
    type: 'parallel',
    label: '并行',
    description: '多分支并行执行',
    icon: ForkOutlined,
  },
  {
    type: 'delay',
    label: '延迟',
    description: '等待指定时间',
    icon: ClockCircleOutlined,
  },
  {
    type: 'end',
    label: '结束',
    description: '工作流出口节点',
    icon: CheckCircleOutlined,
  },
]

function onDragStart(event: DragEvent, node: NodeTypeItem) {
  if (event.dataTransfer) {
    event.dataTransfer.setData('application/vueflow', JSON.stringify(node))
    event.dataTransfer.effectAllowed = 'move'
  }
}
</script>

<style scoped>
.node-panel {
  width: 200px;
  height: 100%;
  padding: 12px;
  border-right: 1px solid #d9d9d9;
  background: #fafafa;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.panel-title {
  margin: 0 0 12px 0;
  font-size: 14px;
  font-weight: 600;
  color: #262626;
  display: flex;
  align-items: center;
  gap: 6px;
}
.node-list {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.node-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid #e8e8e8;
  border-radius: 8px;
  background: #fff;
  cursor: grab;
  transition: all 0.2s ease;
  user-select: none;
}
.node-item:hover {
  border-color: #1677ff;
  box-shadow: 0 2px 8px rgba(22, 119, 255, 0.15);
}
.node-item:active {
  cursor: grabbing;
}
.node-icon {
  font-size: 20px;
  flex-shrink: 0;
}
.node-type-start .node-icon { color: #52c41a; }
.node-type-agent .node-icon { color: #1677ff; }
.node-type-tool .node-icon { color: #722ed1; }
.node-type-hitl .node-icon { color: #fa8c16; }
.node-type-condition .node-icon { color: #eb2f96; }
.node-type-parallel .node-icon { color: #13c2c2; }
.node-type-delay .node-icon { color: #8c8c8c; }
.node-type-end .node-icon { color: #f5222d; }

.node-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.node-name {
  font-size: 13px;
  font-weight: 500;
  color: #262626;
}
.node-desc {
  font-size: 11px;
  color: #8c8c8c;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
