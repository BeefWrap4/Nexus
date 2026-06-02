<template>
  <div>
    <a-page-header title="执行记录" @back="$router.back()" />
    <a-table :columns="columns" :dataSource="runs" rowKey="id">
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'status'">
          <a-tag :color="statusColor(record.status)">{{ record.status }}</a-tag>
        </template>
        <template v-if="column.key === 'action'">
          <a-button size="small" @click="viewRun(record.id)">查看</a-button>
        </template>
      </template>
    </a-table>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import type { WorkflowRun } from '@/types'

const router = useRouter()
const columns = [
  { title: 'Run ID', dataIndex: 'id', key: 'id' },
  { title: '状态', dataIndex: 'status', key: 'status' },
  { title: '触发方式', dataIndex: 'trigger_type', key: 'trigger' },
  { title: '开始时间', dataIndex: 'started_at', key: 'started' },
  { title: '操作', key: 'action' },
]

const runs = ref<WorkflowRun[]>([
  { id: 'run-001', workflow_id: '1', status: 'completed', trigger_type: 'manual', started_at: '2026-06-02T10:00:00Z', completed_at: '2026-06-02T10:00:12Z' },
])

function statusColor(status: string) {
  const colors: Record<string, string> = { completed: 'green', running: 'blue', failed: 'red', paused: 'orange' }
  return colors[status] || 'default'
}

function viewRun(id: string) {
  router.push(`/runs/${id}`)
}
</script>