<template>
  <a-modal
    v-model:open="visible"
    :title="task?.title || '审批任务'"
    :width="600"
    :footer="null"
    :closable="true"
    @cancel="handleCancel"
  >
    <a-descriptions v-if="task" :column="1" bordered size="small">
      <a-descriptions-item label="任务ID">{{ task.id }}</a-descriptions-item>
      <a-descriptions-item label="工作流运行">{{ task.run_id }}</a-descriptions-item>
      <a-descriptions-item label="节点">{{ task.node_id }}</a-descriptions-item>
      <a-descriptions-item label="类型">
        <a-tag :color="typeColor(task.task_type)">{{ typeLabel(task.task_type) }}</a-tag>
      </a-descriptions-item>
      <a-descriptions-item label="状态">
        <a-tag :color="statusColor(task.status)">{{ statusLabel(task.status) }}</a-tag>
      </a-descriptions-item>
      <a-descriptions-item label="创建时间">{{ formatTime(task.created_at) }}</a-descriptions-item>
    </a-descriptions>

    <a-divider />

    <div v-if="task?.context">
      <h4>上下文信息</h4>
      <a-card size="small" class="context-card">
        <pre>{{ JSON.stringify(task.context, null, 2) }}</pre>
      </a-card>
    </div>

    <div v-if="task?.task_type === 'select' && task?.options" style="margin-top: 16px">
      <h4>选择选项</h4>
      <a-radio-group v-model:value="selectedOption" style="width: 100%">
        <a-space direction="vertical" style="width: 100%">
          <a-radio v-for="opt in task.options" :key="opt.value" :value="opt.value">
            {{ opt.label }}
          </a-radio>
        </a-space>
      </a-radio-group>
    </div>

    <div v-if="task?.task_type === 'input'" style="margin-top: 16px">
      <h4>输入内容</h4>
      <a-textarea v-model:value="inputValue" :rows="4" placeholder="请输入内容..." />
    </div>

    <div v-if="task?.task_type === 'correct'" style="margin-top: 16px">
      <h4>修正内容</h4>
      <a-textarea v-model:value="correctionValue" :rows="4" placeholder="请输入修正后的内容..." />
    </div>

    <a-divider />

    <div style="display: flex; justify-content: flex-end; gap: 8px">
      <a-button @click="handleCancel">取消</a-button>
      <a-button danger @click="handleReject">拒绝</a-button>
      <a-button type="primary" :loading="loading" @click="handleApprove">通过</a-button>
    </div>
  </a-modal>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import type { HITLTask } from '@/types'

const props = defineProps<{
  task: HITLTask | null
  open: boolean
}>()

const emit = defineEmits<{
  (e: 'update:open', value: boolean): void
  (e: 'approve', taskId: string, payload?: any): void
  (e: 'reject', taskId: string): void
}>()

const visible = ref(props.open)
const loading = ref(false)
const selectedOption = ref<string | null>(null)
const inputValue = ref('')
const correctionValue = ref('')

watch(() => props.open, (val) => {
  visible.value = val
  if (val && props.task) {
    selectedOption.value = null
    inputValue.value = ''
    correctionValue.value = ''
  }
})

watch(visible, (val) => {
  emit('update:open', val)
})

function typeColor(type: string) {
  const colors: Record<string, string> = {
    approve: 'blue',
    select: 'purple',
    input: 'orange',
    correct: 'cyan',
  }
  return colors[type] || 'default'
}

function typeLabel(type: string) {
  const labels: Record<string, string> = {
    approve: '审批确认',
    select: '选项选择',
    input: '内容输入',
    correct: '内容修正',
  }
  return labels[type] || type
}

function statusColor(status: string) {
  const colors: Record<string, string> = {
    pending: 'orange',
    approved: 'green',
    rejected: 'red',
    timeout: 'default',
  }
  return colors[status] || 'default'
}

function statusLabel(status: string) {
  const labels: Record<string, string> = {
    pending: '待处理',
    approved: '已通过',
    rejected: '已拒绝',
    timeout: '已超时',
  }
  return labels[status] || status
}

function formatTime(iso: string) {
  return new Date(iso).toLocaleString('zh-CN')
}

function handleCancel() {
  visible.value = false
}

function handleApprove() {
  if (!props.task) return
  loading.value = true
  let payload: any = undefined
  if (props.task.task_type === 'select') {
    payload = { selected: selectedOption.value }
  } else if (props.task.task_type === 'input') {
    payload = { input: inputValue.value }
  } else if (props.task.task_type === 'correct') {
    payload = { correction: correctionValue.value }
  }
  emit('approve', props.task.id, payload)
  loading.value = false
  visible.value = false
}

function handleReject() {
  if (!props.task) return
  loading.value = true
  emit('reject', props.task.id)
  loading.value = false
  visible.value = false
}
</script>

<style scoped>
.context-card pre {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 12px;
}
</style>
