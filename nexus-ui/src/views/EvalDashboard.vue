<template>
  <div>
    <a-page-header title="Eval 评估" sub-title="自动化评估与回归测试">
      <template #extra>
        <a-button type="primary" @click="showCreateModal = true">
          <PlusOutlined /> 新建评估
        </a-button>
      </template>
    </a-page-header>

    <a-table
      :columns="columns"
      :data-source="evals"
      :loading="loading"
      row-key="id"
      style="margin-top: 16px"
    >
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'status'">
          <a-tag :color="statusColor(record.status)">{{ record.status }}</a-tag>
        </template>
        <template v-if="column.key === 'dataset_size'">
          {{ record.dataset?.length || 0 }}
        </template>
        <template v-if="column.key === 'action'">
          <a-button type="link" @click="runEval(record.id)" :loading="runningId === record.id">
            运行
          </a-button>
          <a-button type="link" @click="viewResults(record)">结果</a-button>
          <a-button type="link" danger @click="deleteEval(record.id)">删除</a-button>
        </template>
      </template>
    </a-table>

    <!-- Create Modal -->
    <a-modal
      v-model:open="showCreateModal"
      title="新建评估"
      @ok="handleCreate"
      :confirm-loading="createLoading"
    >
      <a-form :model="form" layout="vertical">
        <a-form-item label="名称" required>
          <a-input v-model:value="form.name" placeholder="评估名称" />
        </a-form-item>
        <a-form-item label="评估类型">
          <a-select v-model:value="form.eval_type">
            <a-select-option value="exact_match">精确匹配</a-select-option>
            <a-select-option value="llm_judge">LLM Judge</a-select-option>
            <a-select-option value="contains">包含子串</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="数据集 (JSON)" required>
          <a-textarea
            v-model:value="datasetStr"
            :rows="6"
            placeholder='[{&quot;input&quot;: &quot;What is 2+2?&quot;, &quot;expected&quot;: &quot;4&quot;}]'
          />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- Results Modal -->
    <a-modal v-model:open="resultsVisible" title="评估结果" width="700px" :footer="null">
      <template v-if="currentResults">
        <a-descriptions bordered :column="2">
          <a-descriptions-item label="总条数">{{ currentResults.total }}</a-descriptions-item>
          <a-descriptions-item label="通过">{{ currentResults.passed }}</a-descriptions-item>
          <a-descriptions-item label="失败">{{ currentResults.failed }}</a-descriptions-item>
          <a-descriptions-item label="通过率">{{ (currentResults.pass_rate * 100).toFixed(1) }}%</a-descriptions-item>
          <a-descriptions-item label="平均分">{{ currentResults.avg_score }}</a-descriptions-item>
        </a-descriptions>
        <a-divider />
        <a-table
          :columns="detailColumns"
          :data-source="currentResults.details"
          row-key="index"
          :pagination="{ pageSize: 10 }"
          size="small"
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'passed'">
              <a-tag :color="record.passed ? 'green' : 'red'">
                {{ record.passed ? '通过' : '失败' }}
              </a-tag>
            </template>
          </template>
        </a-table>
      </template>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import { PlusOutlined } from '@ant-design/icons-vue'
import { api } from '@/utils/api'

const loading = ref(false)
const createLoading = ref(false)
const showCreateModal = ref(false)
const evals = ref<any[]>([])
const runningId = ref<string | null>(null)
const resultsVisible = ref(false)
const currentResults = ref<any>(null)

const columns = [
  { title: '名称', dataIndex: 'name', key: 'name' },
  { title: '类型', dataIndex: 'eval_type', key: 'eval_type' },
  { title: '状态', key: 'status' },
  { title: '数据集', key: 'dataset_size' },
  { title: '创建时间', dataIndex: 'created_at', key: 'created_at' },
  { title: '操作', key: 'action' },
]

const detailColumns = [
  { title: '#', dataIndex: 'index', width: 50 },
  { title: '输入', dataIndex: 'input', ellipsis: true },
  { title: '期望', dataIndex: 'expected', ellipsis: true },
  { title: '实际', dataIndex: 'actual', ellipsis: true },
  { title: '分数', dataIndex: 'score', width: 80 },
  { title: '结果', key: 'passed', width: 80 },
]

const form = reactive({
  name: '',
  eval_type: 'exact_match',
})
const datasetStr = ref('[\n  {"input": "What is 2+2?", "expected": "4"}\n]')

function statusColor(status: string) {
  const map: Record<string, string> = {
    pending: 'default',
    running: 'blue',
    completed: 'green',
  }
  return map[status] || 'default'
}

async function fetchEvals() {
  loading.value = true
  try {
    const res = await api.get('/evals/evals')
    evals.value = res.data
  } catch (e: any) {
    message.error(e.response?.data?.detail || '获取失败')
  } finally {
    loading.value = false
  }
}

async function handleCreate() {
  if (!form.name || !datasetStr.value) {
    message.warning('请填写名称和数据集')
    return
  }
  createLoading.value = true
  try {
    const dataset = JSON.parse(datasetStr.value)
    await api.post('/evals/evals', {
      name: form.name,
      eval_type: form.eval_type,
      dataset,
    })
    message.success('创建成功')
    showCreateModal.value = false
    resetForm()
    fetchEvals()
  } catch (e: any) {
    message.error(e.response?.data?.detail || '创建失败')
  } finally {
    createLoading.value = false
  }
}

async function runEval(id: string) {
  runningId.value = id
  try {
    await api.post(`/evals/evals/${id}/run`)
    message.success('评估已启动（后台运行）')
  } catch (e: any) {
    message.error(e.response?.data?.detail || '启动失败')
  } finally {
    runningId.value = null
  }
}

function viewResults(record: any) {
  if (!record.results) {
    message.info('暂无结果')
    return
  }
  currentResults.value = record.results
  resultsVisible.value = true
}

async function deleteEval(id: string) {
  try {
    await api.delete(`/evals/evals/${id}`)
    message.success('删除成功')
    fetchEvals()
  } catch (e: any) {
    message.error(e.response?.data?.detail || '删除失败')
  }
}

function resetForm() {
  form.name = ''
  form.eval_type = 'exact_match'
  datasetStr.value = '[\n  {"input": "What is 2+2?", "expected": "4"}\n]'
}

onMounted(fetchEvals)
</script>
