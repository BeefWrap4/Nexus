<template>
  <div>
    <a-page-header :title="t('codeReview.title')" :sub-title="t('codeReview.subtitle')">
      <template #extra>
        <a-button type="primary" @click="submitReview" :loading="reviewing">
          <PlayCircleOutlined /> {{ t('codeReview.startReview') }}
        </a-button>
      </template>
    </a-page-header>

    <a-row :gutter="16">
      <!-- 输入区 -->
      <a-col :span="8">
        <a-card :title="t('codeReview.reviewConfig')" size="small">
          <a-form layout="vertical">
            <a-form-item :label="t('codeReview.language')">
              <a-select v-model:value="config.language">
                <a-select-option value="auto">{{ t('codeReview.autoDetect') }}</a-select-option>
                <a-select-option value="python">Python</a-select-option>
                <a-select-option value="javascript">JavaScript</a-select-option>
                <a-select-option value="typescript">TypeScript</a-select-option>
                <a-select-option value="java">Java</a-select-option>
                <a-select-option value="go">Go</a-select-option>
                <a-select-option value="rust">Rust</a-select-option>
              </a-select>
            </a-form-item>
            <a-form-item :label="t('codeReview.focusAreas')">
              <a-select v-model:value="config.focus_areas" mode="multiple">
                <a-select-option value="security">{{ t('codeReview.security') }}</a-select-option>
                <a-select-option value="performance">{{ t('codeReview.performance') }}</a-select-option>
                <a-select-option value="maintainability">{{ t('codeReview.maintainability') }}</a-select-option>
                <a-select-option value="correctness">{{ t('codeReview.correctness') }}</a-select-option>
                <a-select-option value="style">{{ t('codeReview.style') }}</a-select-option>
              </a-select>
            </a-form-item>
            <a-form-item :label="t('codeReview.strictness')">
              <a-radio-group v-model:value="config.strictness">
                <a-radio-button value="strict">{{ t('codeReview.strict') }}</a-radio-button>
                <a-radio-button value="normal">{{ t('codeReview.normal') }}</a-radio-button>
                <a-radio-button value="relaxed">{{ t('codeReview.relaxed') }}</a-radio-button>
              </a-radio-group>
            </a-form-item>
          </a-form>
        </a-card>

        <a-card :title="t('codeReview.code')" size="small" style="margin-top: 12px">
          <a-tabs v-model:activeKey="inputMode">
            <a-tab-pane key="diff" :tab="t('codeReview.pasteDiff')">
              <a-textarea v-model:value="diffContent" :rows="15" :placeholder="t('codeReview.pasteDiff') + '...'"/>
            </a-tab-pane>
            <a-tab-pane key="code" :tab="t('codeReview.pasteCode')">
              <a-textarea v-model:value="diffContent" :rows="15" :placeholder="t('codeReview.pasteCode') + '...'"/>
            </a-tab-pane>
          </a-tabs>
        </a-card>
      </a-col>

      <!-- 报告区 -->
      <a-col :span="8">
        <a-card :title="t('codeReview.reviewReport')" size="small">
          <template v-if="report">
            <div style="text-align: center; margin: 16px 0">
              <a-progress type="circle" :percent="report.score * 10" :width="80"
                :format="() => `${report.score}/10`"
                :stroke-color="{ '0%': '#ff4d4f', '50%': '#faad14', '100%': '#52c41a' }"/>
            </div>

            <div v-if="report.strengths?.length" style="margin-bottom: 12px">
              <h4 style="color: #52c41a">✅ {{ t('codeReview.strengths') }}</h4>
              <ul style="padding-left: 20px">
                <li v-for="s in report.strengths" :key="s">{{ s }}</li>
              </ul>
            </div>
            <div v-if="report.risks?.length">
              <h4 style="color: #faad14">⚠️ {{ t('codeReview.risks') }}</h4>
              <ul style="padding-left: 20px">
                <li v-for="r in report.risks" :key="r">{{ r }}</li>
              </ul>
            </div>
          </template>
          <a-empty v-else :description="t('codeReview.clickToStart')"/>
        </a-card>

        <!-- Findings -->
        <a-card :title="t('codeReview.findings')" size="small" style="margin-top: 12px">
          <template v-if="findings.length">
            <a-list item-layout="vertical" :data-source="findings">
              <template #renderItem="{ item, index }">
                <a-list-item>
                  <a-list-item-meta>
                    <template #title>
                      <span :style="{ color: severityColor(item.severity) }">
                        {{ severityIcon(item.severity) }} #{{ index + 1 }} {{ item.title }}
                      </span>
                    </template>
                    <template #description>
                      <div style="font-size: 12px; color: #999">{{ item.file }}:{{ item.line }} · {{ item.category }}</div>
                      <p style="margin-top: 8px">{{ item.description }}</p>
                      <div v-if="item.suggestion" style="background: #f6f6f6; padding: 8px; border-radius: 4px; margin-top: 8px">
                        <strong>{{ t('codeReview.suggestion') }}:</strong> {{ item.suggestion }}
                      </div>
                    </template>
                  </a-list-item-meta>
                </a-list-item>
              </template>
            </a-list>
          </template>
          <a-empty v-else :description="t('codeReview.noFindings')"/>
        </a-card>
      </a-col>

      <!-- 追问区 -->
      <a-col :span="8">
        <a-card :title="t('codeReview.followUp')" size="small">
          <div style="max-height: 400px; overflow-y: auto; margin-bottom: 12px">
            <div v-for="(msg, i) in followUpMessages" :key="i" style="margin-bottom: 12px">
              <div v-if="msg.role === 'user'" style="text-align: right">
                <a-tag color="blue">{{ t('codeReview.you') }}</a-tag>
                <div style="background: #e6f7ff; padding: 8px; border-radius: 8px; display: inline-block; max-width: 80%; text-align: left">
                  {{ msg.content }}
                </div>
              </div>
              <div v-else>
                <a-tag color="green">{{ t('codeReview.ai') }}</a-tag>
                <div style="background: #f6ffed; padding: 8px; border-radius: 8px; display: inline-block; max-width: 80%">
                  {{ msg.content }}
                </div>
              </div>
            </div>
          </div>
          <a-input-search v-model:value="followUpInput" :placeholder="t('codeReview.followUp') + ': ...'"
            @search="sendFollowUp" :loading="followUpLoading"/>
        </a-card>

        <!-- 流式状态 -->
        <a-card :title="t('codeReview.reviewProgress')" size="small" style="margin-top: 12px" v-if="reviewing">
          <div v-for="chunk in streamChunks" :key="chunk.index"
               style="font-family: monospace; font-size: 12px; color: #666; margin-bottom: 4px">
            {{ chunk.text }}
          </div>
          <a-spin v-if="reviewing" style="margin-left: 8px"/>
        </a-card>
      </a-col>
    </a-row>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue'
import { message } from 'ant-design-vue'
import { PlayCircleOutlined } from '@ant-design/icons-vue'
import { useI18n } from 'vue-i18n'
import { api } from '@/utils/api'

const { t } = useI18n()

const reviewing = ref(false)
const diffContent = ref('')
const inputMode = ref('diff')
const report = ref<any>(null)
const findings = ref<any[]>([])
const streamChunks = ref<any[]>([])
const followUpInput = ref('')
const followUpLoading = ref(false)
const followUpMessages = ref<{ role: string; content: string }[]>([])

const config = reactive({
  language: 'auto',
  focus_areas: ['security', 'performance', 'maintainability', 'correctness'],
  strictness: 'normal',
})

function severityColor(s: string) {
  return { critical: '#ff4d4f', warning: '#faad14', suggestion: '#1890ff' }[s] || '#666'
}

function severityIcon(s: string) {
  return { critical: '🔴', warning: '🟡', suggestion: '🔵' }[s] || '⚪'
}

async function submitReview() {
  if (!diffContent.value.trim()) {
    message.warning(t('codeReview.pleasePasteCode'))
    return
  }
  reviewing.value = true
  report.value = null
  findings.value = []
  streamChunks.value = []

  try {
    const res = await api.post('/code-review/reviews', {
      diff_content: diffContent.value,
      language: config.language,
      focus_areas: config.focus_areas.join(', '),
      strictness: config.strictness,
    })
    const runId = res.data.run_id

    // WebSocket 连接获取流式进度
    const { connectWebSocket } = await import('@/utils/websocket')
    const ws = connectWebSocket(runId)
    ws.onmessage = (event: MessageEvent) => {
      const data = JSON.parse(event.data)
      if (data.type === 'stream_chunk') {
        streamChunks.value.push({ index: data.index, text: data.chunk })
      } else if (data.type === 'stream_end') {
        reviewing.value = false
        fetchResult(runId)
      }
    }
    ws.onerror = () => {
      reviewing.value = false
      message.error(t('codeReview.connectionInterrupted'))
      setTimeout(() => fetchResult(runId), 2000)
    }
  } catch (e: any) {
    reviewing.value = false
    message.error(e.response?.data?.detail || t('codeReview.submitFailed'))
  }
}

async function fetchResult(runId: string) {
  try {
    const res = await api.get(`/code-review/reviews/${runId}`)
    const result = res.data.result || {}
    if (result.review_report) {
      const parsed = typeof result.review_report === 'string'
        ? JSON.parse(result.review_report)
        : result.review_report
      report.value = parsed.summary
      findings.value = parsed.findings || []
    }
  } catch {
    message.error(t('codeReview.fetchResultFailed'))
  }
}

async function sendFollowUp(query: string) {
  if (!query.trim()) return
  followUpMessages.value.push({ role: 'user', content: query })
  followUpLoading.value = true
  try {
    // 复用审查 API，以追问模式
    const promptText = `关于之前的代码审查，用户追问: ${query}\n\n请针对该问题给出详细解答。`
    const res = await api.post('/code-review/reviews', {
      diff_content: promptText,
      language: config.language,
      strictness: config.strictness,
    })
    followUpMessages.value.push({ role: 'assistant', content: t('codeReview.analyzing') })
    const runId = res.data.run_id
    setTimeout(async () => {
      try {
        const r = await api.get(`/code-review/reviews/${runId}`)
        followUpMessages.value.pop()
        followUpMessages.value.push({
          role: 'assistant',
          content: r.data.result?.output || t('codeReview.cannotGetAnswer'),
        })
      } catch { /* ignore */ }
      followUpLoading.value = false
    }, 5000)
  } catch {
    message.error(t('codeReview.followUpFailed'))
    followUpLoading.value = false
  }
  followUpInput.value = ''
}
</script>
