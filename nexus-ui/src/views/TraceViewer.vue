<template>
  <div>
    <a-page-header title="LLM Trace" sub-title="LLM 调用追踪记录" />

    <a-form layout="inline" style="margin-bottom: 16px">
      <a-form-item label="Run ID">
        <a-input v-model:value="filters.run_id" placeholder="运行ID" style="width: 200px" />
      </a-form-item>
      <a-form-item label="Agent">
        <a-input v-model:value="filters.agent_id" placeholder="Agent ID" style="width: 150px" />
      </a-form-item>
      <a-form-item label="Model">
        <a-input v-model:value="filters.model" placeholder="模型" style="width: 150px" />
      </a-form-item>
      <a-form-item>
        <a-button type="primary" @click="fetchTraces">查询</a-button>
      </a-form-item>
    </a-form>

    <a-table
      :columns="columns"
      :data-source="traces"
      :loading="loading"
      :pagination="{ pageSize: 20 }"
      row-key="id"
    >
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'tokens'">
          <a-tag color="green">{{ record.prompt_tokens }}</a-tag>
          <span style="margin: 0 4px">+</span>
          <a-tag color="orange">{{ record.completion_tokens }}</a-tag>
          <span style="margin: 0 4px">=</span>
          <a-tag color="blue">{{ record.total_tokens }}</a-tag>
        </template>
        <template v-if="column.key === 'latency'">
          <span :style="{ color: record.latency_ms > 5000 ? 'red' : 'inherit' }">
            {{ record.latency_ms }}ms
          </span>
        </template>
        <template v-if="column.key === 'cache_hit'">
          <a-tag v-if="record.cache_hit === true" color="green">命中</a-tag>
          <a-tag v-else-if="record.cache_hit === false" color="default">未命中</a-tag>
          <span v-else>-</span>
        </template>
        <template v-if="column.key === 'action'">
          <a-button type="link" @click="showDetail(record)">详情</a-button>
        </template>
      </template>
    </a-table>

    <!-- Detail Modal -->
    <a-modal v-model:open="detailVisible" title="Trace 详情" width="800px" :footer="null">
      <template v-if="detail">
        <a-descriptions bordered :column="1" size="small">
          <a-descriptions-item label="Model">{{ detail.model }}</a-descriptions-item>
          <a-descriptions-item label="Provider">{{ detail.provider }}</a-descriptions-item>
          <a-descriptions-item label="Latency">{{ detail.latency_ms }}ms</a-descriptions-item>
          <a-descriptions-item label="Tokens">
            prompt={{ detail.prompt_tokens }}, completion={{ detail.completion_tokens }}, total={{ detail.total_tokens }}
          </a-descriptions-item>
          <a-descriptions-item label="Retry">{{ detail.retry_count }}</a-descriptions-item>
          <a-descriptions-item label="Fallback">{{ detail.fallback_model || '-' }}</a-descriptions-item>
          <a-descriptions-item label="Cache Hit">{{ detail.cache_hit ? '是' : (detail.cache_hit === false ? '否' : '-') }}</a-descriptions-item>
        </a-descriptions>

        <a-divider />
        <h4>System Prompt</h4>
        <pre style="background: #f6f6f6; padding: 12px; border-radius: 4px; white-space: pre-wrap; max-height: 200px; overflow: auto">
          {{ detail.system_prompt }}
        </pre>

        <h4>User Prompt</h4>
        <pre style="background: #f6f6f6; padding: 12px; border-radius: 4px; white-space: pre-wrap; max-height: 200px; overflow: auto">
          {{ detail.user_prompt }}
        </pre>

        <h4>Response</h4>
        <pre style="background: #f6f6f6; padding: 12px; border-radius: 4px; white-space: pre-wrap; max-height: 300px; overflow: auto">
          {{ detail.response_content }}
        </pre>

        <template v-if="detail.tool_calls?.length">
          <h4>Tool Calls</h4>
          <pre style="background: #f6f6f6; padding: 12px; border-radius: 4px">{{ JSON.stringify(detail.tool_calls, null, 2) }}</pre>
        </template>
      </template>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import { api } from '@/utils/api'

const loading = ref(false)
const traces = ref<any[]>([])
const detailVisible = ref(false)
const detail = ref<any>(null)

const filters = reactive({
  run_id: '',
  agent_id: '',
  model: '',
})

const columns = [
  { title: 'Model', dataIndex: 'model', key: 'model', width: 150 },
  { title: 'Agent', dataIndex: 'agent_id', key: 'agent_id', width: 120 },
  { title: 'Node', dataIndex: 'node_id', key: 'node_id', width: 120 },
  { title: 'Tokens', key: 'tokens' },
  { title: 'Latency', key: 'latency', width: 100 },
  { title: 'Retry', dataIndex: 'retry_count', width: 80 },
  { title: 'Cache', key: 'cache_hit', width: 90 },
  { title: 'Time', dataIndex: 'created_at', width: 180 },
  { title: 'Action', key: 'action', width: 80 },
]

async function fetchTraces() {
  loading.value = true
  try {
    const params: any = {}
    if (filters.run_id) params.run_id = filters.run_id
    if (filters.agent_id) params.agent_id = filters.agent_id
    if (filters.model) params.model = filters.model
    const res = await api.get('/traces/traces', { params })
    traces.value = res.data.items || []
  } catch (e: any) {
    message.error(e.response?.data?.detail || '获取失败')
  } finally {
    loading.value = false
  }
}

async function showDetail(record: any) {
  try {
    const res = await api.get(`/traces/traces/${record.id}`)
    detail.value = res.data
    detailVisible.value = true
  } catch (e: any) {
    message.error('获取详情失败')
  }
}

onMounted(fetchTraces)
</script>
