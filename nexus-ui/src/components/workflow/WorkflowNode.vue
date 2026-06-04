<template>
  <div :class="['workflow-node', `node-${nodeType}`, { selected }]">
    <!-- 输入连接点 -->
    <Handle 
      v-if="showTarget" 
      type="target" 
      :position="Position.Top" 
      :style="handleStyle"
    />

    <!-- 节点内容 -->
    <div class="node-content">
      <!-- 图标 -->
      <component v-if="nodeIcon" :is="nodeIcon" class="node-icon" />
      
      <!-- 标签 -->
      <div class="node-label">{{ label }}</div>
      
      <!-- 徽章（可选） -->
      <div v-if="badge" class="node-badge">{{ badge }}</div>
      
      <!-- 状态指示器 -->
      <StatusBadge 
        v-if="status" 
        :status="status" 
        :show-icon="false"
        class="node-status"
      />
    </div>

    <!-- 输出连接点 -->
    <Handle 
      v-if="showSource" 
      type="source" 
      :position="Position.Bottom"
      :id="sourceHandleId"
      :style="handleStyle"
    />
    
    <!-- 条件节点的额外输出点 -->
    <Handle 
      v-if="nodeType === 'condition'" 
      type="source" 
      :position="Position.Bottom" 
      id="false"
      style="left: 70%"
    />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Handle, Position } from '@vue-flow/core'
import { 
  PlayCircleOutlined,
  RobotOutlined,
  ToolOutlined,
  PauseCircleOutlined,
  QuestionCircleOutlined,
  ForkOutlined,
  ClockCircleOutlined,
  CheckCircleOutlined,
} from '@ant-design/icons-vue'
import StatusBadge from './common/StatusBadge.vue'

interface Props {
  label?: string
  nodeType?: string
  selected?: boolean
  status?: string
  badge?: string
  showTarget?: boolean
  showSource?: boolean
  sourceHandleId?: string
  data?: Record<string, any>
}

const props = withDefaults(defineProps<Props>(), {
  label: '',
  nodeType: 'default',
  selected: false,
  showTarget: true,
  showSource: true,
  sourceHandleId: undefined,
  data: () => ({}),
})

// 根据节点类型选择图标
const nodeIcon = computed(() => {
  const iconMap: Record<string, any> = {
    start: PlayCircleOutlined,
    agent: RobotOutlined,
    tool: ToolOutlined,
    hitl: PauseCircleOutlined,
    condition: QuestionCircleOutlined,
    parallel: ForkOutlined,
    delay: ClockCircleOutlined,
    end: CheckCircleOutlined,
  }
  return iconMap[props.nodeType] || undefined
})

// 连接点样式
const handleStyle = {
  width: '12px',
  height: '12px',
  border: '2px solid #fff',
}
</script>

<style scoped>
.workflow-node {
  position: relative;
  padding: 12px 16px;
  border-radius: 8px;
  background: white;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  min-width: 160px;
  transition: all 0.3s ease;
  cursor: pointer;
}

.workflow-node:hover {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  transform: translateY(-2px);
}

.workflow-node.selected {
  box-shadow: 0 0 0 2px #1677ff;
}

/* 不同类型节点的样式 */
.node-start {
  border-left: 4px solid #52c41a;
}

.node-agent {
  border-left: 4px solid #722ed1;
}

.node-tool {
  border-left: 4px solid #1677ff;
}

.node-hitl {
  border-left: 4px solid #fa8c16;
}

.node-condition {
  border-left: 4px solid #eb2f96;
}

.node-parallel {
  border-left: 4px solid #13c2c2;
}

.node-delay {
  border-left: 4px solid #faad14;
}

.node-end {
  border-left: 4px solid #52c41a;
}

.node-content {
  display: flex;
  align-items: center;
  gap: 8px;
}

.node-icon {
  font-size: 20px;
  flex-shrink: 0;
}

.node-label {
  font-weight: 500;
  font-size: 14px;
  color: #333;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.node-badge {
  background: #1677ff;
  color: white;
  font-size: 10px;
  padding: 2px 6px;
  border-radius: 10px;
  font-weight: bold;
  flex-shrink: 0;
}

.node-status {
  margin-top: 4px;
  font-size: 11px;
}

/* 选中状态高亮 */
.workflow-node.selected .node-label {
  color: #1677ff;
}
</style>
