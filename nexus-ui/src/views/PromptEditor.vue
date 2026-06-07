<template>
  <div>
    <a-page-header title="Prompt 管理" sub-title="Prompt 模板编辑器">
      <template #extra>
        <a-button type="primary" @click="showCreateModal = true">
          <PlusOutlined /> 新建模板
        </a-button>
      </template>
    </a-page-header>

    <!-- Prompt List -->
    <a-table
      :columns="columns"
      :data-source="prompts"
      :loading="loading"
      row-key="id"
      style="margin-top: 16px"
      @expand="handleExpand"
    >
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'version'">
          <a-tag color="blue">v{{ record.current_version }}</a-tag>
        </template>
        <template v-if="column.key === 'action'">
          <a-button type="link" @click="openEditor(record)">编辑</a-button>
          <a-button type="link" danger @click="deletePrompt(record.id)">删除</a-button>
        </template>
      </template>
      <template #expandedRowRender="{ record }">
        <div style="padding: 12px 0">
          <h4>版本历史</h4>
          <a-list size="small" :data-source="record.versions || []">
            <template #renderItem="{ item }">
              <a-list-item>
                <span>v{{ item.version }}</span>
                <span style="margin-left: 16px; color: #999">{{ item.change_notes }}</span>
                <span style="margin-left: 16px; color: #999">{{ formatDate(item.created_at) }}</span>
              </a-list-item>
            </template>
          </a-list>
        </div>
      </template>
    </a-table>

    <!-- Create/Edit Modal -->
    <a-modal
      v-model:open="showCreateModal"
      :title="editingPrompt ? '编辑 Prompt' : '新建 Prompt'"
      @ok="handleSave"
      :confirm-loading="saveLoading"
      width="800px"
    >
      <a-form :model="form" layout="vertical">
        <a-form-item label="名称" required>
          <a-input v-model:value="form.name" placeholder="模板名称" />
        </a-form-item>
        <a-form-item label="描述">
          <a-input v-model:value="form.description" placeholder="描述" />
        </a-form-item>
        <a-form-item label="模板内容" required>
          <a-textarea
            v-model:value="form.content"
            :rows="8"
            placeholder="支持 Jinja2 语法，如: Hello {{ name }}!"
          />
        </a-form-item>
        <a-form-item label="变量（逗号分隔）">
          <a-input
            v-model:value="variablesStr"
            placeholder="name, language, tone"
          />
        </a-form-item>
        <a-form-item label="变更说明">
          <a-input v-model:value="form.change_notes" placeholder="变更说明" />
        </a-form-item>
        <a-divider />
        <h4>实时预览</h4>
        <div style="background: #f6f6f6; padding: 12px; border-radius: 4px">
          <div v-for="v in form.variables" :key="v" style="margin-bottom: 8px">
            <a-input
              v-model:value="previewVars[v]"
              :placeholder="v"
              size="small"
              style="width: 200px"
            />
          </div>
          <pre style="margin-top: 12px; white-space: pre-wrap">{{ previewContent }}</pre>
        </div>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { message } from 'ant-design-vue'
import { PlusOutlined } from '@ant-design/icons-vue'
import { api } from '@/utils/api'
import { promptsApi } from '@/api'

const loading = ref(false)
const saveLoading = ref(false)
const showCreateModal = ref(false)
const prompts = ref<any[]>([])
const editingPrompt = ref<any>(null)
const previewVars = ref<Record<string, string>>({})

const columns = [
  { title: '名称', dataIndex: 'name', key: 'name' },
  { title: '类型', dataIndex: 'template_type', key: 'template_type' },
  { title: '当前版本', key: 'version' },
  { title: '描述', dataIndex: 'description', key: 'description' },
  { title: '操作', key: 'action' },
]

const form = reactive({
  name: '',
  description: '',
  content: 'Hello {{ name }}!',
  variables: [] as string[],
  change_notes: '',
})

const variablesStr = computed({
  get: () => form.variables.join(', '),
  set: (val: string) => {
    form.variables = val.split(',').map(s => s.trim()).filter(Boolean)
  },
})

const previewContent = computed(() => {
  let result = form.content
  for (const [key, val] of Object.entries(previewVars.value)) {
    result = result.replace(new RegExp(`{{\\s*${key}\\s*}}`, 'g'), val || `{{${key}}}`)
  }
  return result
})

watch(() => form.variables, (vars) => {
  for (const v of vars) {
    if (!(v in previewVars.value)) {
      previewVars.value[v] = ''
    }
  }
}, { immediate: true })

async function fetchPrompts() {
  loading.value = true
  try {
    const res = await api.get('/prompts/prompts')
    prompts.value = res.data
  } catch (e: any) {
    message.error(e.response?.data?.detail || '获取失败')
  } finally {
    loading.value = false
  }
}

async function handleExpand(expanded: boolean, record: any) {
  if (expanded && !record.versions) {
    try {
      const res = await promptsApi.getVersions(record.id)
      record.versions = res.data
    } catch (e) {
      record.versions = []
    }
  }
}

function openEditor(record: any) {
  editingPrompt.value = record
  form.name = record.name
  form.description = record.description || ''
  form.change_notes = ''
  // 获取当前版本内容
  promptsApi.getContent(record.id).then((res: any) => {
    form.content = res.data.content
    form.variables = res.data.variables || []
  })
  showCreateModal.value = true
}

async function handleSave() {
  if (!form.name || !form.content) {
    message.warning('请填写名称和内容')
    return
  }

  saveLoading.value = true
  try {
    if (editingPrompt.value) {
      await api.put(`/prompts/prompts/${editingPrompt.value.id}`, {
        name: form.name,
        description: form.description,
        content: form.content,
        variables: form.variables,
        change_notes: form.change_notes || 'Updated',
      })
      message.success('更新成功')
    } else {
      await api.post('/prompts/prompts', {
        name: form.name,
        description: form.description,
        content: form.content,
        variables: form.variables,
        change_notes: form.change_notes || 'Initial version',
      })
      message.success('创建成功')
    }
    showCreateModal.value = false
    editingPrompt.value = null
    resetForm()
    fetchPrompts()
  } catch (e: any) {
    message.error(e.response?.data?.detail || '保存失败')
  } finally {
    saveLoading.value = false
  }
}

async function deletePrompt(id: string) {
  try {
    await api.delete(`/prompts/prompts/${id}`)
    message.success('删除成功')
    fetchPrompts()
  } catch (e: any) {
    message.error(e.response?.data?.detail || '删除失败')
  }
}

function resetForm() {
  form.name = ''
  form.description = ''
  form.content = 'Hello {{ name }}!'
  form.variables = []
  form.change_notes = ''
  previewVars.value = {}
}

function formatDate(d: string) {
  return d ? new Date(d).toLocaleString() : '-'
}

onMounted(fetchPrompts)
</script>
