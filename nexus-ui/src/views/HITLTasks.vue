<template>
  <ErrorBoundary>
    <div>
      <a-page-header title="待审批任务" />

      <a-row :gutter="16" style="margin-bottom: 16px">
        <a-col :span="24">
          <a-segmented v-model:value="filterStatus" :options="filterOptions" />
        </a-col>
      </a-row>

      <EmptyState v-if="!loading && filteredTasks.length === 0" description="暂无审批任务" />

      <DataTable
        v-else
        :columns="columns"
        :data-source="filteredTasks"
        :loading="loading"
        row-key="id"
        :pagination="{ pageSize: 10 }"
        @refresh="fetchTasks"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'type'">
            <StatusBadge
              :status="record.task_type"
              :custom-text="typeLabel(record.task_type)"
              :show-icon="false"
            />
          </template>
          <template v-if="column.key === 'status'">
            <StatusBadge :status="record.status" :custom-text="statusLabel(record.status)" />
          </template>
          <template v-if="column.key === 'action'">
            <a-space>
              <a-button v-if="record.status === 'pending'" type="primary" size="small" @click="openApproval(record)">审批</a-button>
              <a-button size="small" @click="openApproval(record)">详情</a-button>
            </a-space>
          </template>
        </template>
      </DataTable>

      <HITLApproval
        v-model:open="approvalOpen"
        :task="selectedTask"
        @approve="handleApprove"
        @reject="handleReject"
      />
    </div>
  </ErrorBoundary>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import api from '@/api'
import DataTable from '@/components/common/DataTable.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import ErrorBoundary from '@/components/common/ErrorBoundary.vue'
import HITLApproval from '@/components/HITLApproval.vue'
import type { HITLTask } from '@/types'

const loading = ref(false)
const tasks = ref<HITLTask[]>([])
const approvalOpen = ref(false)
const selectedTask = ref<HITLTask | null>(null)
const filterStatus = ref('pending')

const filterOptions = [
  { label: '待处理', value: 'pending' },
  { label: '已通过', value: 'approved' },
  { label: '已拒绝', value: 'rejected' },
  { label: '全部', value: 'all' },
]

const filteredTasks = computed(() => {
  if (filterStatus.value === 'all') return tasks.value
  return tasks.value.filter(t => t.status === filterStatus.value)
})

const columns = [
  { title: '标题', dataIndex: 'title', key: 'title' },
  { title: '类型', key: 'type' },
  { title: '工作流运行', dataIndex: 'run_id', key: 'run_id' },
  { title: '节点', dataIndex: 'node_id', key: 'node_id' },
  { title: '状态', key: 'status' },
  { title: '创建时间', dataIndex: 'created_at', key: 'created_at' },
  { title: '操作', key: 'action' },
]

function typeLabel(type: string) {
  const labels: Record<string, string> = {
    approve: '审批确认',
    select: '选项选择',
    input: '内容输入',
    correct: '内容修正',
  }
  return labels[type] || type
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

function openApproval(task: HITLTask) {
  selectedTask.value = task
  approvalOpen.value = true
}

async function handleApprove(taskId: string, payload?: any) {
  try {
    await api.post(`/hitl/tasks/${taskId}/respond`, { ...payload, decision: 'approve' })
    message.success('任务已审批通过')
    await fetchTasks()
  } catch {
    message.error('审批失败')
  }
}

async function handleReject(taskId: string) {
  try {
    await api.post(`/hitl/tasks/${taskId}/respond`, { decision: 'reject' })
    message.warning('任务已拒绝')
    await fetchTasks()
  } catch {
    message.error('拒绝失败')
  }
}

async function fetchTasks() {
  loading.value = true
  try {
    const resp = await api.get('/hitl/tasks')
    tasks.value = resp.data
  } catch {
    message.error('获取任务列表失败')
    tasks.value = [
      { id: '1', run_id: 'run-001', node_id: 'hitl-1', task_type: 'approve', title: '合同审查结果确认', status: 'pending', created_at: '2026-06-02T10:00:00Z' },
      { id: '2', run_id: 'run-002', node_id: 'hitl-2', task_type: 'select', title: '选择报表类型', status: 'pending', created_at: '2026-06-02T10:05:00Z' },
    ]
  } finally {
    loading.value = false
  }
}

onMounted(fetchTasks)
</script>
