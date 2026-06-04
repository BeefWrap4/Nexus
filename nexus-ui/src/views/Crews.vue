<template>
  <ErrorBoundary>
    <div>
      <a-page-header title="Crew 团队" sub-title="多 Agent 协作编排">
        <template #extra>
          <a-button type="primary" @click="$router.push('/crews/new')">
            <PlusOutlined /> 创建 Crew
          </a-button>
        </template>
      </a-page-header>

      <EmptyState v-if="!loading && crews.length === 0" description="暂无 Crew 团队">
        <template #extra>
          <a-button type="primary" @click="$router.push('/crews/new')">
            <PlusOutlined /> 创建第一个Crew
          </a-button>
        </template>
      </EmptyState>

      <DataTable
        v-else
        :columns="columns"
        :data-source="crews"
        :loading="loading"
        row-key="id"
        :pagination="{ pageSize: 10 }"
        style="margin-top: 16px"
        @refresh="fetchCrews"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'name'">
            <a-space>
              <TeamOutlined />
              <span>{{ record.name }}</span>
            </a-space>
          </template>
          <template v-if="column.key === 'mode'">
            <StatusBadge :status="record.mode" :show-icon="false" />
          </template>
          <template v-if="column.key === 'agent_count'">
            <span>{{ record.agents?.length || 0 }}</span>
          </template>
          <template v-if="column.key === 'action'">
            <a-space>
              <a-button size="small" @click="$router.push(`/crews/${record.id}/edit`)">编辑</a-button>
              <a-button size="small" @click="openRunModal(record)">执行</a-button>
              <a-button size="small" danger @click="deleteCrew(record.id)">删除</a-button>
            </a-space>
          </template>
        </template>
      </DataTable>

      <a-modal v-model:open="runModalOpen" title="执行 Crew" @ok="runCrew" :confirm-loading="running">
        <a-form layout="vertical">
          <a-form-item label="任务描述" required>
            <a-textarea v-model:value="runTask" :rows="4" placeholder="输入需要 Crew 协作完成的任务..." />
          </a-form-item>
        </a-form>
      </a-modal>
    </div>
  </ErrorBoundary>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import { PlusOutlined, TeamOutlined } from '@ant-design/icons-vue'
import api from '@/api'
import DataTable from '@/components/common/DataTable.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import ErrorBoundary from '@/components/common/ErrorBoundary.vue'

interface Crew {
  id: string
  name: string
  description: string
  mode: string
  agents: any[]
}

const crews = ref<Crew[]>([])
const loading = ref(false)
const runModalOpen = ref(false)
const running = ref(false)
const runTask = ref('')
const runningCrewId = ref('')

const columns = [
  { title: '名称', key: 'name' },
  { title: '描述', dataIndex: 'description', key: 'description' },
  { title: '模式', key: 'mode' },
  { title: 'Agent 数', key: 'agent_count' },
  { title: '操作', key: 'action' },
]

async function fetchCrews() {
  loading.value = true
  try {
    const { data } = await api.get('/crews')
    crews.value = data || []
  } catch {
    message.error('获取 Crew 列表失败')
    crews.value = []
  } finally {
    loading.value = false
  }
}

function openRunModal(crew: Crew) {
  runningCrewId.value = crew.id
  runTask.value = ''
  runModalOpen.value = true
}

async function runCrew() {
  if (!runTask.value.trim()) {
    message.warning('请输入任务描述')
    return
  }
  running.value = true
  try {
    const { data } = await api.post(`/crews/${runningCrewId.value}/run`, {
      task_description: runTask.value,
    })
    message.success('Crew 执行完成')
    runModalOpen.value = false
    console.log('Crew run result:', data)
  } catch (e: any) {
    message.error(e.response?.data?.detail || '执行失败')
  } finally {
    running.value = false
  }
}

async function deleteCrew(id: string) {
  try {
    await api.delete(`/crews/${id}`)
    message.success('Crew 已删除')
    await fetchCrews()
  } catch {
    message.error('删除失败')
  }
}

onMounted(fetchCrews)
</script>
