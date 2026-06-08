<template>
  <ErrorBoundary>
    <a-page-header title="账单" sub-title="管理您的订阅和支付方式" />
    <a-spin :spinning="loading">
      <a-row :gutter="24">
        <a-col :span="16">
          <a-card title="当前用量">
            <a-descriptions :column="1" bordered>
              <a-descriptions-item label="计划">
                <a-tag :color="planColor[usage.plan] || 'default'">{{ usage.plan?.toUpperCase() }}</a-tag>
              </a-descriptions-item>
              <a-descriptions-item label="计费周期">
                {{ formatDate(usage.current_period_start) }} ~ {{ formatDate(usage.current_period_end) }}
              </a-descriptions-item>
              <a-descriptions-item v-for="(value, key) in usage.usage" :key="key" :label="metricLabel(String(key))">
                <a-progress
                  :percent="Math.min(100, Math.round((value / (usage.caps?.[key] || 1)) * 100))"
                  :status="(value / (usage.caps?.[key] || 1)) > 0.8 ? 'exception' : 'normal'"
                />
                <span class="usage-text">{{ value.toLocaleString() }} / {{ (usage.caps?.[key] || 0).toLocaleString() }}</span>
              </a-descriptions-item>
            </a-descriptions>
          </a-card>
        </a-col>
        <a-col :span="8">
          <a-card title="操作">
            <a-space direction="vertical" style="width: 100%">
              <a-button type="primary" block @click="changePlan" :disabled="usage.plan === 'enterprise'">
                升级计划
              </a-button>
              <a-button block @click="openPortal" :disabled="usage.plan === 'free'">
                管理订阅
              </a-button>
            </a-space>
          </a-card>
        </a-col>
      </a-row>
    </a-spin>
  </ErrorBoundary>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { billingApi } from '@/api'
import ErrorBoundary from '@/components/common/ErrorBoundary.vue'

const router = useRouter()
const loading = ref(false)
const usage = ref<any>({})

const planColor: Record<string, string> = {
  free: 'default',
  pro: 'blue',
  enterprise: 'gold',
}

function metricLabel(metric: string): string {
  return { tokens: 'Tokens', api_calls: 'API Calls', storage_bytes: '存储' }[metric] || metric
}

function formatDate(ts: number): string {
  return ts ? new Date(ts * 1000).toLocaleDateString('zh-CN') : '—'
}

async function fetchUsage() {
  loading.value = true
  try {
    const resp = await billingApi.getUsage()
    usage.value = resp.data
  } catch (e: any) {
    message.error('无法加载账单信息')
  } finally {
    loading.value = false
  }
}

async function openPortal() {
  try {
    const resp = await billingApi.openPortal()
    window.location.href = resp.data.portal_url
  } catch (e: any) {
    message.error(e?.response?.data?.detail || '无法打开订阅管理')
  }
}

function changePlan() {
  router.push('/pricing')
}

onMounted(fetchUsage)
</script>
