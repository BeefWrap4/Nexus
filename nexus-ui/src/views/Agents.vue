<template>
  <ErrorBoundary>
    <div>
      <a-space style="margin-bottom: 16px">
        <a-button type="primary" @click="openCreate">
          <PlusOutlined /> 创建Agent
        </a-button>
        <a-button @click="fetchAgents"><ReloadOutlined /> 刷新</a-button>
      </a-space>

      <EmptyState v-if="!loading && agents.length === 0" description="暂无Agent">
        <template #extra>
          <a-button type="primary" @click="openCreate">
            <PlusOutlined /> 创建第一个Agent
          </a-button>
        </template>
      </EmptyState>

      <DataTable
        v-else
        :columns="columns"
        :data-source="agents"
        :loading="loading"
        row-key="id"
        :pagination="{ pageSize: 10 }"
        @refresh="fetchAgents"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'name'">
            <a-space>
              <RobotOutlined />
              <span>{{ record.name }}</span>
            </a-space>
          </template>
          <template v-if="column.key === 'model'">
            <a-tag>{{ record.model_config?.model || 'default' }}</a-tag>
          </template>
          <template v-if="column.key === 'status'">
            <StatusBadge status="active" type="success" custom-text="运行中" />
          </template>
          <template v-if="column.key === 'action'">
            <a-space>
              <a-button size="small" @click="openEdit(record)">编辑</a-button>
              <a-button size="small" danger @click="deleteAgent(record.id)">删除</a-button>
            </a-space>
          </template>
        </template>
      </DataTable>

      <a-modal
        v-model:open="modalOpen"
        :title="isEdit ? '编辑Agent' : '创建Agent'"
        :confirm-loading="saving"
        @ok="saveAgent"
      >
        <a-form :model="form" layout="vertical">
          <a-form-item label="名称" required>
            <a-input v-model:value="form.name" placeholder="Agent名称" />
          </a-form-item>
          <a-form-item label="角色" required>
            <a-input v-model:value="form.role" placeholder="如: 法务专家" />
          </a-form-item>
          <a-form-item label="目标" required>
            <a-textarea v-model:value="form.goal" :rows="3" placeholder="描述该Agent的目标" />
          </a-form-item>
          <a-form-item label="模型">
            <a-select v-model:value="form.model" placeholder="选择模型">
              <a-select-option value="gpt-4o">GPT-4o</a-select-option>
              <a-select-option value="gpt-4o-mini">GPT-4o Mini</a-select-option>
              <a-select-option value="claude-3-sonnet">Claude 3 Sonnet</a-select-option>
              <a-select-option value="glm-4">GLM-4</a-select-option>
            </a-select>
          </a-form-item>
          <a-form-item label="温度">
            <a-slider v-model:value="form.temperature" :min="0" :max="2" :step="0.1" />
          </a-form-item>
        </a-form>
      </a-modal>
    </div>
  </ErrorBoundary>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import { PlusOutlined, ReloadOutlined, RobotOutlined } from '@ant-design/icons-vue'
import api from '@/api'
import DataTable from '@/components/common/DataTable.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import ErrorBoundary from '@/components/common/ErrorBoundary.vue'
import type { Agent } from '@/types'

const agents = ref<Agent[]>([])
const loading = ref(false)
const modalOpen = ref(false)
const saving = ref(false)
const isEdit = ref(false)
const editingId = ref('')

const form = reactive({
  name: '',
  role: '',
  goal: '',
  model: 'gpt-4o',
  temperature: 0.7,
})

const columns = [
  { title: '名称', key: 'name' },
  { title: '角色', dataIndex: 'role', key: 'role' },
  { title: '目标', dataIndex: 'goal', key: 'goal' },
  { title: '模型', key: 'model' },
  { title: '状态', key: 'status' },
  { title: '操作', key: 'action' },
]

async function fetchAgents() {
  loading.value = true
  try {
    const resp = await api.get('/agents')
    agents.value = resp.data
  } catch {
    message.error('获取Agents失败')
    agents.value = [
      { id: '1', name: '合同审查员', role: '法务专家', goal: '审查合同条款风险', model_config: { model: 'gpt-4o' }, created_at: '2026-05-01' },
    ]
  } finally {
    loading.value = false
  }
}

function openCreate() {
  isEdit.value = false
  editingId.value = ''
  form.name = ''
  form.role = ''
  form.goal = ''
  form.model = 'gpt-4o'
  form.temperature = 0.7
  modalOpen.value = true
}

function openEdit(agent: Agent) {
  isEdit.value = true
  editingId.value = agent.id
  form.name = agent.name
  form.role = agent.role
  form.goal = agent.goal
  form.model = agent.model_config?.model || 'gpt-4o'
  form.temperature = agent.model_config?.temperature || 0.7
  modalOpen.value = true
}

async function saveAgent() {
  if (!form.name || !form.role || !form.goal) {
    message.warning('请填写必填项')
    return
  }
  saving.value = true
  try {
    const payload = {
      name: form.name,
      role: form.role,
      goal: form.goal,
      model_config: { model: form.model, temperature: form.temperature },
    }
    if (isEdit.value) {
      await api.put(`/agents/${editingId.value}`, payload)
      message.success('Agent已更新')
    } else {
      await api.post('/agents', payload)
      message.success('Agent已创建')
    }
    modalOpen.value = false
    await fetchAgents()
  } catch {
    message.error('保存失败')
  } finally {
    saving.value = false
  }
}

async function deleteAgent(id: string) {
  try {
    await api.delete(`/agents/${id}`)
    message.success('Agent已删除')
    await fetchAgents()
  } catch {
    message.error('删除失败')
  }
}

onMounted(fetchAgents)
</script>
