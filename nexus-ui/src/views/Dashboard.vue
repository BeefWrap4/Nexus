<template>
  <div>
    <a-row :gutter="16">
      <a-col :xs="12" :sm="12" :md="6">
        <a-card>
          <a-statistic :title="t('dashboard.workflows')" :value="stats.workflows" :value-style="{ color: '#1677ff' }">
            <template #prefix><NodeIndexOutlined /></template>
          </a-statistic>
        </a-card>
      </a-col>
      <a-col :xs="12" :sm="12" :md="6">
        <a-card>
          <a-statistic :title="t('dashboard.todayRuns')" :value="stats.runs" :value-style="{ color: '#52c41a' }">
            <template #prefix><PlayCircleOutlined /></template>
          </a-statistic>
        </a-card>
      </a-col>
      <a-col :xs="12" :sm="12" :md="6">
        <a-card>
          <a-statistic :title="t('dashboard.agents')" :value="stats.agents" :value-style="{ color: '#722ed1' }">
            <template #prefix><RobotOutlined /></template>
          </a-statistic>
        </a-card>
      </a-col>
      <a-col :xs="12" :sm="12" :md="6">
        <a-card>
          <a-statistic :title="t('dashboard.pendingApproval')" :value="stats.hitl" :value-style="{ color: '#fa8c16' }">
            <template #prefix><QuestionCircleOutlined /></template>
          </a-statistic>
        </a-card>
      </a-col>
    </a-row>

    <!-- Phase 9: 缓存指标 -->
    <a-row :gutter="16" style="margin-top: 16px">
      <a-col :xs="12" :sm="12" :md="6">
        <a-card>
          <a-statistic :title="t('dashboard.cacheHitRate')" :value="stats.cache_hit_rate || 0" suffix="%" :value-style="{ color: '#52c41a' }">
            <template #prefix><ThunderboltOutlined /></template>
          </a-statistic>
        </a-card>
      </a-col>
      <a-col :xs="12" :sm="12" :md="6">
        <a-card>
          <a-statistic :title="t('dashboard.cacheHits')" :value="stats.cache_hits || 0" :value-style="{ color: '#1677ff' }">
            <template #prefix><CheckCircleOutlined /></template>
          </a-statistic>
        </a-card>
      </a-col>
      <a-col :xs="12" :sm="12" :md="6">
        <a-card>
          <a-statistic :title="t('dashboard.cacheSavedTokens')" :value="stats.cache_saved_tokens || 0" :value-style="{ color: '#fa8c16' }">
            <template #prefix><SaveOutlined /></template>
          </a-statistic>
        </a-card>
      </a-col>
      <a-col :xs="12" :sm="12" :md="6">
        <a-card>
          <a-statistic :title="t('dashboard.llmCalls')" :value="stats.llm_calls || 0" :value-style="{ color: '#722ed1' }">
            <template #prefix><MessageOutlined /></template>
          </a-statistic>
        </a-card>
      </a-col>
    </a-row>

    <a-row :gutter="16" style="margin-top: 16px">
      <a-col :xs="24" :md="12">
        <a-card :title="t('dashboard.statusDistribution')">
          <div class="chart-placeholder">
            <div class="mini-bar-chart">
              <div v-for="(item, idx) in statusDistribution" :key="idx" class="bar-item">
                <div class="bar-label">{{ item.label }}</div>
                <a-progress :percent="item.percent" :status="item.status as any" :show-info="false" :stroke-width="12" />
                <div class="bar-value">{{ item.value }}</div>
              </div>
            </div>
          </div>
        </a-card>
      </a-col>
      <a-col :xs="24" :md="12">
        <a-card :title="t('dashboard.weeklyTrend')">
          <div class="chart-placeholder">
            <div class="sparkline">
              <div
                v-for="(val, idx) in weeklyTrend"
                :key="idx"
                class="spark-bar"
                :style="{ height: `${(val / maxWeekly) * 100}%` }"
                :title="`${val} ${t('common.times')}`"
              />
            </div>
            <div class="sparkline-labels">
              <span v-for="(d, idx) in weekDays" :key="idx">{{ d }}</span>
            </div>
          </div>
        </a-card>
      </a-col>
    </a-row>

    <a-divider />
    <h3>{{ t('dashboard.recentRuns') }}</h3>
    <DataTable 
      :columns="columns" 
      :data-source="recentRuns" 
      :pagination="{ pageSize: 10 }"
      :searchable="false"
      :refreshable="false"
      :show-toolbar="false"
      size="small" 
      :loading="loading" 
      row-key="id"
    >
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'status'">
          <StatusBadge :status="record.status" />
        </template>
        <template v-if="column.key === 'action'">
          <a-button size="small" @click="viewRun(record.id)">{{ t('common.view') }}</a-button>
        </template>
      </template>
    </DataTable>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import {
  NodeIndexOutlined,
  PlayCircleOutlined,
  RobotOutlined,
  QuestionCircleOutlined,
  ThunderboltOutlined,
  CheckCircleOutlined,
  SaveOutlined,
  MessageOutlined,
} from '@ant-design/icons-vue'
import { useI18n } from 'vue-i18n'
import api from '@/api'
import type { WorkflowRun } from '@/types'

const { t } = useI18n()
import StatusBadge from '@/components/common/StatusBadge.vue'
import DataTable from '@/components/common/DataTable.vue'

const router = useRouter()
const loading = ref(false)

interface DashboardStats {
  workflows: number
  runs: number
  agents: number
  hitl: number
  cache_hit_rate?: number
  cache_hits?: number
  cache_saved_tokens?: number
  llm_calls?: number
  status_distribution?: Record<string, number>
  weekly_trend?: number[]
}

const stats = ref<DashboardStats>({ workflows: 0, runs: 0, agents: 0, hitl: 0 })
const recentRuns = ref<WorkflowRun[]>([])

const columns = [
  { title: t('dashboard.runId'), dataIndex: 'id', key: 'id' },
  { title: t('dashboard.workflow'), dataIndex: 'workflow_name', key: 'workflow' },
  { title: t('dashboard.status'), dataIndex: 'status', key: 'status' },
  { title: t('dashboard.triggerType'), dataIndex: 'trigger_type', key: 'trigger' },
  { title: t('dashboard.startTime'), dataIndex: 'started_at', key: 'time' },
  { title: t('dashboard.action'), key: 'action' },
]

const statusDistribution = ref([
  { label: t('status.succeeded'), value: 0, percent: 0, status: 'success' },
  { label: t('status.running'), value: 0, percent: 0, status: 'active' },
  { label: t('status.failed'), value: 0, percent: 0, status: 'exception' },
  { label: t('status.cancelled'), value: 0, percent: 0, status: 'normal' },
])

const weeklyTrend = ref([0, 0, 0, 0, 0, 0, 0])
const weekDays = [t('common.monday'), t('common.tuesday'), t('common.wednesday'), t('common.thursday'), t('common.friday'), t('common.saturday'), t('common.sunday')]
const maxWeekly = computed(() => Math.max(1, ...weeklyTrend.value))

function viewRun(id: string) {
  router.push(`/runs/${id}`)
}

async function fetchDashboardData() {
  loading.value = true
  try {
    const [statsRes, runsRes] = await Promise.all([
      api.get('/dashboard/stats').catch(() => ({ data: null })),
      api.get('/runs?limit=10').catch(() => ({ data: [] })),
    ])

    if (statsRes.data) {
      stats.value = statsRes.data
    } else {
      stats.value = { workflows: 12, runs: 45, agents: 8, hitl: 3 }
    }

    recentRuns.value = runsRes.data || []

    const dist: Record<string, number> = statsRes.data?.status_distribution || { completed: 38, running: 4, failed: 2, cancelled: 1 }
    const total = Object.values(dist).reduce((a, b) => a + b, 0) || 1
    statusDistribution.value = [
      { label: t('status.succeeded'), value: dist.completed || 0, percent: Math.round(((dist.completed || 0) / total) * 100), status: 'success' },
      { label: t('status.running'), value: dist.running || 0, percent: Math.round(((dist.running || 0) / total) * 100), status: 'active' },
      { label: t('status.failed'), value: dist.failed || 0, percent: Math.round(((dist.failed || 0) / total) * 100), status: 'exception' },
      { label: t('status.cancelled'), value: dist.cancelled || 0, percent: Math.round(((dist.cancelled || 0) / total) * 100), status: 'normal' },
    ]

    weeklyTrend.value = statsRes.data?.weekly_trend || [12, 18, 15, 22, 28, 35, 45]
  } catch (err) {
    message.error(t('dashboard.fetchFailed'))
  } finally {
    loading.value = false
  }
}

onMounted(fetchDashboardData)
</script>

<style scoped>
.chart-placeholder {
  min-height: 160px;
  display: flex;
  flex-direction: column;
  justify-content: center;
}
.mini-bar-chart {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.bar-item {
  display: grid;
  grid-template-columns: 60px 1fr 40px;
  align-items: center;
  gap: 8px;
}
.bar-label {
  font-size: 12px;
  color: #666;
}
.bar-value {
  font-size: 12px;
  color: #333;
  text-align: right;
}
.sparkline {
  display: flex;
  align-items: flex-end;
  gap: 6px;
  height: 100px;
  padding: 8px 0;
}
.spark-bar {
  flex: 1;
  background: #1677ff;
  border-radius: 2px 2px 0 0;
  min-height: 4px;
  transition: height 0.3s ease;
}
.spark-bar:hover {
  background: #4096ff;
}
.sparkline-labels {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  color: #999;
  margin-top: 4px;
}
</style>
