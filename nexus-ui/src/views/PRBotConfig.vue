<template>
  <div>
    <a-page-header title="PR 审查机器人" sub-title="GitHub Pull Request Auto-Review Bot">
      <template #extra>
        <a-button type="primary" @click="refreshStatus" :loading="loadingStatus">
          <ReloadOutlined /> 刷新状态
        </a-button>
      </template>
    </a-page-header>

    <a-row :gutter="16">
      <!-- 配置状态 -->
      <a-col :span="8">
        <a-card title="配置状态" size="small">
          <a-descriptions :column="1" bordered size="small">
            <a-descriptions-item label="Webhook Secret">
              <a-tag :color="configStatus.webhook_secret_configured ? 'green' : 'red'">
                {{ configStatus.webhook_secret_configured ? '已配置' : '未配置' }}
              </a-tag>
            </a-descriptions-item>
            <a-descriptions-item label="GitHub Token">
              <a-tag :color="configStatus.github_token_configured ? 'green' : 'red'">
                {{ configStatus.github_token_configured ? '已配置' : '未配置' }}
              </a-tag>
            </a-descriptions-item>
          </a-descriptions>

          <a-alert
            v-if="!configStatus.webhook_secret_configured || !configStatus.github_token_configured"
            type="warning"
            show-icon
            style="margin-top: 12px"
          >
            <template #message>环境变量缺失</template>
            <template #description>
              请在服务器环境变量中设置：<br/>
              <code>GITHUB_WEBHOOK_SECRET</code> — 用于验证 GitHub Webhook 签名<br/>
              <code>GITHUB_TOKEN</code> — 用于调用 GitHub API
            </template>
          </a-alert>

          <div style="margin-top: 16px">
            <h4>Webhook URL</h4>
            <a-input
              :value="webhookUrl"
              readonly
              style="margin-bottom: 8px"
            >
              <template #addonAfter>
                <a-button type="link" size="small" @click="copyWebhookUrl">
                  <CopyOutlined />
                </a-button>
              </template>
            </a-input>
            <p style="font-size: 12px; color: #999">
              在 GitHub 仓库 Settings → Webhooks 中添加此 URL，Content type 选 <code>application/json</code>，事件选 <code>Pull requests</code>。
            </p>
          </div>
        </a-card>

        <!-- 模拟触发 -->
        <a-card title="模拟触发" size="small" style="margin-top: 12px">
          <a-form layout="vertical">
            <a-form-item label="仓库 Owner">
              <a-input v-model:value="simulateForm.owner" placeholder="e.g. test-org" />
            </a-form-item>
            <a-form-item label="仓库名">
              <a-input v-model:value="simulateForm.repo" placeholder="e.g. test-repo" />
            </a-form-item>
            <a-form-item label="PR Number">
              <a-input-number v-model:value="simulateForm.pull_number" :min="1" style="width: 100%" />
            </a-form-item>
            <a-form-item>
              <a-button type="primary" @click="simulateWebhook" :loading="simulating">
                触发审查
              </a-button>
            </a-form-item>
          </a-form>
        </a-card>
      </a-col>

      <!-- 审查历史 -->
      <a-col :span="16">
        <a-card title="审查历史" size="small">
          <a-empty v-if="!history.length" description="暂无审查记录" />
          <a-timeline v-else>
            <a-timeline-item
              v-for="item in history"
              :key="item.run_id"
              :color="statusColor(item.status)"
            >
              <div style="display: flex; justify-content: space-between; align-items: center">
                <span>
                  <strong>{{ item.owner }}/{{ item.repo }}#{{ item.pull_number }}</strong>
                </span>
                <a-tag :color="statusColor(item.status)">{{ statusText(item.status) }}</a-tag>
              </div>
              <div style="font-size: 12px; color: #999; margin-top: 4px">
                Run ID: <code>{{ item.run_id }}</code> · {{ formatTime(item.created_at) }}
              </div>
              <div v-if="item.status === 'completed' && item.result" style="margin-top: 8px">
                <a-collapse ghost>
                  <a-collapse-panel key="1" header="查看结果">
                    <pre style="background: #f6f6f6; padding: 12px; border-radius: 4px; overflow-x: auto; font-size: 12px">{{ JSON.stringify(item.result, null, 2) }}</pre>
                  </a-collapse-panel>
                </a-collapse>
              </div>
            </a-timeline-item>
          </a-timeline>
        </a-card>
      </a-col>
    </a-row>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, computed } from 'vue'
import { message } from 'ant-design-vue'
import { ReloadOutlined, CopyOutlined } from '@ant-design/icons-vue'
import api from '@/api'

interface ConfigStatus {
  webhook_secret_configured: boolean
  github_token_configured: boolean
}

interface HistoryItem {
  run_id: string
  owner: string
  repo: string
  pull_number: number
  status: string
  result?: any
  created_at: string
}

const configStatus = ref<ConfigStatus>({
  webhook_secret_configured: false,
  github_token_configured: false,
})
const loadingStatus = ref(false)
const simulating = ref(false)
const history = ref<HistoryItem[]>([])

const simulateForm = reactive({
  owner: '',
  repo: '',
  pull_number: 1,
})

const webhookUrl = computed(() => {
  const base = (import.meta as any).env.VITE_API_BASE_URL || window.location.origin
  return `${base.replace('/api/v1', '')}/api/v1/webhooks/github`
})

function statusColor(status: string) {
  return {
    completed: 'green',
    running: 'blue',
    failed: 'red',
    pending: 'orange',
  }[status] || 'gray'
}

function statusText(status: string) {
  return {
    completed: '已完成',
    running: '运行中',
    failed: '失败',
    pending: '等待中',
  }[status] || status
}

function formatTime(ts: string) {
  if (!ts) return ''
  return new Date(ts).toLocaleString('zh-CN')
}

async function refreshStatus() {
  loadingStatus.value = true
  try {
    const res = await api.get('/webhooks/github/config')
    configStatus.value = res.data
  } catch (e: any) {
    message.error('获取配置状态失败')
  } finally {
    loadingStatus.value = false
  }
}

async function simulateWebhook() {
  if (!simulateForm.owner || !simulateForm.repo) {
    message.warning('请填写 owner 和 repo')
    return
  }
  simulating.value = true
  try {
    // 构造一个模拟的 GitHub webhook payload
    const payload = {
      action: 'opened',
      pull_request: {
        number: simulateForm.pull_number,
        diff_url: `https://github.com/${simulateForm.owner}/${simulateForm.repo}/pull/${simulateForm.pull_number}.diff`,
      },
      repository: {
        name: simulateForm.repo,
        owner: { login: simulateForm.owner },
      },
    }
    const res = await api.post('/webhooks/github', payload, {
      headers: {
        'X-GitHub-Event': 'pull_request',
        'X-Hub-Signature-256': 'sha256=test-simulate-signature',
      },
    })
    message.success(`审查已启动: Run ${res.data.run_id}`)
    history.value.unshift({
      run_id: res.data.run_id,
      owner: simulateForm.owner,
      repo: simulateForm.repo,
      pull_number: simulateForm.pull_number,
      status: 'running',
      created_at: new Date().toISOString(),
    })
  } catch (e: any) {
    message.error(e.response?.data?.detail || '触发失败')
  } finally {
    simulating.value = false
  }
}

function copyWebhookUrl() {
  navigator.clipboard.writeText(webhookUrl.value).then(() => {
    message.success('已复制')
  })
}

onMounted(() => {
  refreshStatus()
})
</script>
