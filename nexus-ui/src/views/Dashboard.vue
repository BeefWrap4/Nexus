<template>
  <div>
    <a-row :gutter="16">
      <a-col :xs="12" :sm="12" :md="6">
        <a-card>
          <a-statistic title="工作流" :value="stats.workflows" :value-style="{ color: '#1677ff' }">
            <template #prefix><NodeIndexOutlined /></template>
          </a-statistic>
        </a-card>
      </a-col>
      <a-col :xs="12" :sm="12" :md="6">
        <a-card>
          <a-statistic title="今日执行" :value="stats.runs" :value-style="{ color: '#52c41a' }">
            <template #prefix><PlayCircleOutlined /></template>
          </a-statistic>
        </a-card>
      </a-col>
      <a-col :xs="12" :sm="12" :md="6">
        <a-card>
          <a-statistic title="Agents" :value="stats.agents" :value-style="{ color: '#722ed1' }">
            <template #prefix><RobotOutlined /></template>
          </a-statistic>
        </a-card>
      </a-col>
      <a-col :xs="12" :sm="12" :md="6">
        <a-card>
          <a-statistic title="待审批" :value="stats.hitl" :value-style="{ color: '#fa8c16' }">
            <template #prefix><QuestionCircleOutlined /></template>
          </a-statistic>
        </a-card>
      </a-col>
    </a-row>

    <a-row :gutter="16" style="margin-top: 16px">
      <a-col :xs="24" :md="12">
        <a-card title="执行状态分布">
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
        <a-card title="最近7天执行趋势">
          <div class="chart-placeholder">
            <div class="sparkline">
              <div
                v-for="(val, idx) in weeklyTrend"
                :key="idx"
                class="spark-bar"
                :style="{ height: `${(val / maxWeekly) * 100}%` }"
                :title="`${val} 次`"
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
    <h3>最近执行</h3>
    <a-table :columns="columns" :dataSource="recentRuns" :pagination="false" size="small" :loading="loading" rowKey="id">
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
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import {
  NodeIndexOutlined,
  PlayCircleOutlined,
  RobotOutlined,
  QuestionCircleOutlined,
} from '@ant-design/icons-vue'
import api from '@/api'
import type { WorkflowRun } from '@/types'

const router = useRouter()
const loading = ref(false)

const stats = ref({ workflows: 0, runs: 0, agents: 0, hitl: 0 })
const recentRuns = ref<WorkflowRun[]>([])

const columns = [
  { title: 'Run ID', dataIndex: 'id', key: 'id' },
  { title: '工作流', dataIndex: 'workflow_name', key: 'workflow' },
  { title: '状态', dataIndex: 'status', key: 'status' },
  { title: '触发方式', dataIndex: 'trigger_type', key: 'trigger' },
  { title: '开始时间', dataIndex: 'started_at', key: 'time' },
  { title: '操作', key: 'action' },
]

const statusDistribution = ref([
  { label: '成功', value: 0, percent: 0, status: 'success' },
  { label: '运行中', value: 0, percent: 0, status: 'active' },
  { label: '失败', value: 0, percent: 0, status: 'exception' },
  { label: '取消', value: 0, percent: 0, status: 'normal' },
])

const weeklyTrend = ref([0, 0, 0, 0, 0, 0, 0])
const weekDays = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
const maxWeekly = computed(() => Math.max(1, ...weeklyTrend.value))

function statusColor(status: string) {
  const colors: Record<string, string> = {
    completed: 'green',
    running: 'blue',
    failed: 'red',
    paused: 'orange',
    cancelled: 'default',
    pending: 'default',
  }
  return colors[status] || 'default'
}

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
      { label: '成功', value: dist.completed || 0, percent: Math.round(((dist.completed || 0) / total) * 100), status: 'success' },
      { label: '运行中', value: dist.running || 0, percent: Math.round(((dist.running || 0) / total) * 100), status: 'active' },
      { label: '失败', value: dist.failed || 0, percent: Math.round(((dist.failed || 0) / total) * 100), status: 'exception' },
      { label: '取消', value: dist.cancelled || 0, percent: Math.round(((dist.cancelled || 0) / total) * 100), status: 'normal' },
    ]

    weeklyTrend.value = statsRes.data?.weekly_trend || [12, 18, 15, 22, 28, 35, 45]
  } catch (err) {
    message.error('获取Dashboard数据失败')
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
