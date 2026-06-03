<template>
  <div>
    <a-page-header title="A/B 实验" sub-title="Prompt 版本对比实验" />

    <a-table
      :columns="columns"
      :data-source="experiments"
      :loading="loading"
      row-key="id"
      style="margin-top: 16px"
    >
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'status'">
          <a-tag :color="record.status === 'running' ? 'green' : 'default'">
            {{ record.status }}
          </a-tag>
        </template>
        <template v-if="column.key === 'variants'">
          <a-space>
            <a-tag v-for="v in record.variants" :key="v.name" color="blue">
              {{ v.name }} (v{{ v.template_version }}): {{ v.traffic_percentage }}%
            </a-tag>
          </a-space>
        </template>
        <template v-if="column.key === 'action'">
          <a-button v-if="record.status === 'running'" type="link" @click="pauseExperiment(record.id)">
            暂停
          </a-button>
          <a-button type="link" @click="viewResults(record.id)">结果</a-button>
        </template>
      </template>
    </a-table>

    <!-- Results Modal -->
    <a-modal v-model:open="resultsVisible" title="实验结果" width="700px" :footer="null">
      <template v-if="results">
        <a-descriptions bordered :column="1">
          <a-descriptions-item label="实验名称">{{ results.name }}</a-descriptions-item>
          <a-descriptions-item label="状态">
            <a-tag :color="results.status === 'running' ? 'green' : 'default'">{{ results.status }}</a-tag>
          </a-descriptions-item>
        </a-descriptions>
        <a-divider />
        <a-table
          :columns="resultColumns"
          :data-source="results.variants"
          row-key="name"
          :pagination="false"
        />
      </template>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import { api } from '@/utils/api'

const loading = ref(false)
const experiments = ref<any[]>([])
const resultsVisible = ref(false)
const results = ref<any>(null)

const columns = [
  { title: '名称', dataIndex: 'name', key: 'name' },
  { title: '模板ID', dataIndex: 'template_id', key: 'template_id' },
  { title: '状态', key: 'status' },
  { title: '变体', key: 'variants' },
  { title: '操作', key: 'action' },
]

const resultColumns = [
  { title: '变体', dataIndex: 'name', key: 'name' },
  { title: '版本', dataIndex: 'version', key: 'version' },
  { title: '流量%', dataIndex: 'traffic_percentage', key: 'traffic_percentage' },
  { title: '调用次数', dataIndex: 'total_calls', key: 'total_calls' },
  { title: '平均耗时(ms)', dataIndex: 'avg_latency_ms', key: 'avg_latency_ms' },
  { title: '平均Tokens', dataIndex: 'avg_tokens', key: 'avg_tokens' },
]

async function fetchExperiments() {
  loading.value = true
  try {
    // 简化：直接获取所有实验（实际应分页）
    const res = await api.get('/prompts/experiments')
    experiments.value = res.data || []
  } catch (e: any) {
    message.error(e.response?.data?.detail || '获取失败')
  } finally {
    loading.value = false
  }
}

async function pauseExperiment(id: string) {
  try {
    await api.post(`/experiments/${id}/pause`)
    message.success('已暂停')
    fetchExperiments()
  } catch (e: any) {
    message.error(e.response?.data?.detail || '操作失败')
  }
}

async function viewResults(id: string) {
  try {
    const res = await api.get(`/experiments/${id}/results`)
    results.value = res.data
    resultsVisible.value = true
  } catch (e: any) {
    message.error('获取结果失败')
  }
}

onMounted(fetchExperiments)
</script>
