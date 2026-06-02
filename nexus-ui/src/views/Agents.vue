<template>
  <div>
    <a-space style="margin-bottom: 16px">
      <a-button type="primary" @click="openCreate">
        <PlusOutlined /> 创建Agent
      </a-button>
      <a-button @click="fetchAgents"><ReloadOutlined /> 刷新</a-button>
    </a-space>

    <a-row :gutter="16">
      <a-col v-for="agent in agents" :key="agent.id" :xs="24" :sm="12" :md="8" :lg="6" style="margin-bottom: 16px">
        <a-card hoverable size="small">
          <template #title>
            <div style="display: flex; justify-content: space-between; align-items: center">
              <span><RobotOutlined /> {{ agent.name }}</span>
              <a-dropdown>
                <a-button type="text" size="small"><EllipsisOutlined /></a-button>
                <template #overlay>
                  <a-menu>
                    <a-menu-item key="edit" @click="openEdit(agent)">编辑</a-menu-item>
                    <a-menu-item key="delete" danger @click="deleteAgent(agent.id)">删除</a-menu-item>
                  </a-menu>
                </template>
              </a-dropdown>
            </div>
          </template>
          <p style="color: #666; font-size: 12px; margin: 0"><strong>角色:</strong> {{ agent.role }}</p>
          <p style="color: #666; font-size: 12px; margin: 4px 0 0"><strong>目标:</strong> {{ agent.goal }}</p>
          <p style="color: #999; font-size: 11px; margin: 8px 0 0">模型: {{ agent.model_config?.model || 'default' }}</p>
        </a-card>
      </a-col>
    </a-row>

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
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import { PlusOutlined, ReloadOutlined, RobotOutlined, EllipsisOutlined } from '@ant-design/icons-vue'
import api from '@/api'
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

async function fetchAgents() {
  loading.value = true
  try {
    const { data } = await api.get('/agents')
    agents.value = data
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
