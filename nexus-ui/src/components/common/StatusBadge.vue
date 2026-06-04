<template>
  <a-tag :color="statusColor" class="status-badge">
    <component v-if="icon" :is="icon" style="margin-right: 4px" />
    {{ statusText }}
  </a-tag>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { 
  CheckCircleOutlined, 
  CloseCircleOutlined, 
  ClockCircleOutlined,
  PlayCircleOutlined,
  PauseCircleOutlined
} from '@ant-design/icons-vue'

interface Props {
  status: string
  type?: 'success' | 'warning' | 'error' | 'info' | 'default' | 'processing'
  customText?: string
  showIcon?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  type: 'default',
  showIcon: true
})

// 状态映射配置 - 支持多种业务场景
const statusMap: Record<string, { color: string; text: string; icon?: any }> = {
  // 工作流执行状态
  completed: { color: 'success', text: '已完成', icon: CheckCircleOutlined },
  succeeded: { color: 'success', text: '成功', icon: CheckCircleOutlined },
  running: { color: 'processing', text: '运行中', icon: PlayCircleOutlined },
  failed: { color: 'error', text: '失败', icon: CloseCircleOutlined },
  pending: { color: 'default', text: '待处理', icon: ClockCircleOutlined },
  paused: { color: 'warning', text: '已暂停', icon: PauseCircleOutlined },
  cancelled: { color: 'default', text: '已取消', icon: CloseCircleOutlined },
  
  // 节点执行状态
  waiting: { color: 'default', text: '等待中', icon: ClockCircleOutlined },
  skipped: { color: 'default', text: '已跳过', icon: undefined },
  
  // Crew模式
  hierarchical: { color: 'blue', text: '层级', icon: undefined },
  sequential: { color: 'green', text: '顺序', icon: undefined },
  parallel: { color: 'purple', text: '并行', icon: undefined },
}

const statusConfig = computed(() => {
  const config = statusMap[props.status.toLowerCase()]
  if (config) return config
  
  // 如果没有预设映射，使用自定义类型
  return { 
    color: props.type, 
    text: props.customText || props.status,
    icon: undefined
  }
})

const statusColor = computed(() => statusConfig.value.color)
const statusText = computed(() => statusConfig.value.text)
const icon = computed(() => props.showIcon ? statusConfig.value.icon : undefined)
</script>

<style scoped>
.status-badge {
  font-weight: 500;
  display: inline-flex;
  align-items: center;
}
</style>
