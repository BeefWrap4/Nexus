<template>
  <div>
    <a-space style="margin-bottom: 16px">
      <a-button type="primary" @click="openRegister">
        <PlusOutlined /> 注册工具
      </a-button>
      <a-button @click="fetchTools"><ReloadOutlined /> 刷新</a-button>
    </a-space>

    <a-table :columns="columns" :dataSource="tools" rowKey="id" :loading="loading">
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'status'">
          <a-badge :status="record.status === 'active' ? 'success' : 'default'" :text="record.status === 'active' ? '启用' : '禁用'" />
        </template>
        <template v-if="column.key === 'action'">
          <a-space>
            <a-button size="small" @click="testTool(record)">测试</a-button>
            <a-button size="small" @click="openEdit(record)">编辑</a-button>
            <a-button size="small" danger @click="deleteTool(record.id)">删除</a-button>
          </a-space>
        </template>
      </template>
    </a-table>

    <a-modal
      v-model:open="modalOpen"
      :title="isEdit ? '编辑工具' : '注册工具'"
      :confirm-loading="saving"
      @ok="saveTool"
    >
      <a-form :model="form" layout="vertical">
        <a-form-item label="名称" required>
          <a-input v-model:value="form.name" placeholder="工具名称，如 query_database" />
        </a-form-item>
        <a-form-item label="描述" required>
          <a-textarea v-model:value="form.description" :rows="2" placeholder="描述工具功能" />
        </a-form-item>
        <a-form-item label="类型" required>
          <a-select v-model:value="form.type" placeholder="选择类型">
            <a-select-option value="sql">SQL查询</a-select-option>
            <a-select-option value="http">HTTP接口</a-select-option>
            <a-select-option value="python">Python脚本</a-select-option>
            <a-select-option value="llm">LLM调用</a-select-option>
            <a-select-option value="custom">自定义</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="配置(JSON)">
          <a-textarea v-model:value="form.configJson" :rows="4" placeholder='{"url": "...", "method": "GET"}' />
        </a-form-item>
      </a-form>
    </a-modal>

    <a-modal v-model:open="testModalOpen" title="测试工具" :footer="null" width="600">
      <a-form layout="vertical">
        <a-form-item label="输入参数(JSON)">
          <a-textarea v-model:value="testInput" :rows="4" placeholder='{"query": "SELECT 1"}' />
        </a-form-item>
        <a-button type="primary" :loading="testing" @click="runTest">执行测试</a-button>
      </a-form>
      <a-divider />
      <div v-if="testResult">
        <h4>结果</h4>
        <a-card size="small">
          <pre class="result-block">{{ JSON.stringify(testResult, null, 2) }}</pre>
        </a-card>
      </div>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons-vue'
import api from '@/api'
import type { Tool } from '@/types'

const tools = ref<Tool[]>([])
const loading = ref(false)
const modalOpen = ref(false)
const saving = ref(false)
const isEdit = ref(false)
const editingId = ref('')

const form = reactive({
  name: '',
  description: '',
  type: 'http',
  configJson: '',
})

const testModalOpen = ref(false)
const testInput = ref('{}')
const testing = ref(false)
const testResult = ref<any>(null)
const testingTool = ref<Tool | null>(null)

const columns = [
  { title: '名称', dataIndex: 'name', key: 'name' },
  { title: '描述', dataIndex: 'description', key: 'description' },
  { title: '类型', dataIndex: 'type', key: 'type' },
  { title: '状态', key: 'status' },
  { title: '操作', key: 'action' },
]

async function fetchTools() {
  loading.value = true
  try {
    const { data } = await api.get('/tools')
    tools.value = data
  } catch {
    message.error('获取工具列表失败')
    tools.value = [
      { id: '1', name: 'query_database', description: 'SQL查询', type: 'sql', status: 'active' },
      { id: '2', name: 'send_email', description: '发送邮件', type: 'http', status: 'active' },
    ]
  } finally {
    loading.value = false
  }
}

function openRegister() {
  isEdit.value = false
  editingId.value = ''
  form.name = ''
  form.description = ''
  form.type = 'http'
  form.configJson = ''
  modalOpen.value = true
}

function openEdit(tool: Tool) {
  isEdit.value = true
  editingId.value = tool.id
  form.name = tool.name
  form.description = tool.description
  form.type = tool.type
  form.configJson = JSON.stringify(tool.config || {}, null, 2)
  modalOpen.value = true
}

async function saveTool() {
  if (!form.name || !form.description || !form.type) {
    message.warning('请填写必填项')
    return
  }
  saving.value = true
  try {
    let config = {}
    if (form.configJson) {
      try {
        config = JSON.parse(form.configJson)
      } catch {
        message.error('配置JSON格式错误')
        saving.value = false
        return
      }
    }
    const payload = {
      name: form.name,
      description: form.description,
      type: form.type,
      config,
    }
    if (isEdit.value) {
      await api.put(`/tools/${editingId.value}`, payload)
      message.success('工具已更新')
    } else {
      await api.post('/tools', payload)
      message.success('工具已注册')
    }
    modalOpen.value = false
    await fetchTools()
  } catch {
    message.error('保存失败')
  } finally {
    saving.value = false
  }
}

async function deleteTool(id: string) {
  try {
    await api.delete(`/tools/${id}`)
    message.success('工具已删除')
    await fetchTools()
  } catch {
    message.error('删除失败')
  }
}

function testTool(tool: Tool) {
  testingTool.value = tool
  testInput.value = '{}'
  testResult.value = null
  testModalOpen.value = true
}

async function runTest() {
  if (!testingTool.value) return
  testing.value = true
  try {
    let params = {}
    try {
      params = JSON.parse(testInput.value)
    } catch {
      message.error('输入参数JSON格式错误')
      testing.value = false
      return
    }
    const { data } = await api.post(`/tools/${testingTool.value.id}/test`, params)
    testResult.value = data
  } catch (err: any) {
    testResult.value = { error: err.response?.data?.detail || '测试失败' }
  } finally {
    testing.value = false
  }
}

onMounted(fetchTools)
</script>

<style scoped>
.result-block {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 12px;
  max-height: 300px;
  overflow: auto;
}
</style>
