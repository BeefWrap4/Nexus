<template>
  <div>
    <a-page-header
      title="执行监控"
      :sub-title="`Run: ${runId}`"
      @back="$router.back()"
    >
      <template #extra>
        <a-space>
          <a-tag :color="runStatusColor">{{ runStatus }}</a-tag>
          <a-button v-if="runStatus === 'running'" danger @click="cancelRun">取消</a-button>
          <a-button v-if="runStatus === 'paused'" type="primary" @click="resumeRun">恢复</a-button>
          <a-button @click="refreshRun"><ReloadOutlined /> 刷新</a-button>
        </a-space>
      </template>
    </a-page-header>

    <a-row :gutter="16" style="margin-top: 16px">
      <a-col :span="24">
        <a-card title="节点执行状态" size="small">
          <a-steps :current="currentStep" size="small" direction="horizontal">
            <a-step
              v-for="node in nodeRuns"
              :key="node.id"
              :title="node.node_id"
              :status="nodeStepStatus(node.status)"
            />
          </a-steps>
        </a-card>
      </a-col>
    </a-row>

    <a-timeline style="margin-top: 24px">
      <a-timeline-item
        v-for="node in nodeRuns"
        :key="node.id"
        :color="nodeStatusColor(node.status)"
      >
        <a-card size="small" :body-style="{ padding: '12px' }">
          <div style="display: flex; justify-content: space-between; align-items: center">
            <div>
              <strong>{{ node.node_id }}</strong>
              <a-tag size="small" style="margin-left: 8px">{{ node.node_type }}</a-tag>
            </div>
            <a-tag :color="nodeStatusColor(node.status)">{{ node.status }}</a-tag>
          </div>
          <p v-if="node.started_at" style="margin: 4px 0; color: #999; font-size: 12px">
            开始: {{ formatTime(node.started_at) }}
            <span v-if="node.completed_at"> | 完成: {{ formatTime(node.completed_at) }}</span>
          </p>
          <a-divider v-if="node.input || node.output || node.error" style="margin: 8px 0" />
          <div v-if="node.input">
            <p style="margin: 0; font-size: 12px; color: #666"><strong>输入:</strong></p>
            <pre class="code-block">{{ JSON.stringify(node.input, null, 2) }}</pre>
          </div>
          <!-- 流式输出展示 -->
          <div v-if="streamChunks[node.node_id]?.chunks.length">
            <p style="margin: 0; font-size: 12px; color: #666">
              <strong>流式输出:</strong>
              <a-tag v-if="!streamChunks[node.node_id]?.ended" size="small" color="blue">生成中...</a-tag>
            </p>
            <div class="stream-output">{{ streamChunks[node.node_id].chunks.join('') }}</div>
          </div>

          <div v-if="node.output">
            <p style="margin: 0; font-size: 12px; color: #666"><strong>输出:</strong></p>
            <pre class="code-block">{{ JSON.stringify(node.output, null, 2).substring(0, 500) }}</pre>
          </div>
          <div v-if="node.error">
            <p style="margin: 0; font-size: 12px; color: #ff4d4f"><strong>错误:</strong></p>
            <pre class="code-block error">{{ node.error.message || JSON.stringify(node.error, null, 2) }}</pre>
          </div>
        </a-card>
      </a-timeline-item>
    </a-timeline>

    <a-divider />
    <h4>实时日志 <a-tag v-if="wsConnected" color="green">已连接</a-tag><a-tag v-else color="red">未连接</a-tag></h4>
    <div ref="logContainer" class="log-container">
      <pre v-for="(log, i) in logs" :key="i" :class="logClass(log)">{{ log }}</pre>
      <div v-if="logs.length === 0" class="log-empty">等待日志...</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import { message } from 'ant-design-vue'
import { ReloadOutlined } from '@ant-design/icons-vue'
import { connectWebSocket } from '@/api'
import api from '@/api'
import type { NodeRun } from '@/types'

const route = useRoute()
const runId = computed(() => route.params.id as string)
const runStatus = ref('running')
const nodeRuns = ref<NodeRun[]>([])
const logs = ref<string[]>([])
const wsConnected = ref(false)
const logContainer = ref<HTMLDivElement | null>(null)

// 流式输出存储: { node_id: { chunks: string[], ended: boolean } }
const streamChunks = ref<Record<string, { chunks: string[]; ended: boolean }>>({})

let ws: WebSocket | null = null
let reconnectTimer: ReturnType<typeof setTimeout> | null = null
let heartbeatTimer: ReturnType<typeof setInterval> | null = null
let reconnectAttempts = 0
const MAX_RECONNECT = 5

const currentStep = computed(() => {
  const idx = nodeRuns.value.findIndex(n => n.status === 'running')
  return idx >= 0 ? idx : nodeRuns.value.filter(n => n.status === 'succeeded').length
})

const runStatusColor = computed(() => {
  const colors: Record<string, string> = {
    running: 'blue',
    completed: 'green',
    failed: 'red',
    paused: 'orange',
    cancelled: 'default',
    pending: 'default',
  }
  return colors[runStatus.value] || 'default'
})

function nodeStatusColor(status: string) {
  const colors: Record<string, string> = {
    succeeded: 'green',
    running: 'blue',
    failed: 'red',
    pending: 'gray',
    skipped: 'default',
  }
  return colors[status] || 'gray'
}

function nodeStepStatus(status: string): 'wait' | 'process' | 'finish' | 'error' {
  const map: Record<string, 'wait' | 'process' | 'finish' | 'error'> = {
    pending: 'wait',
    running: 'process',
    succeeded: 'finish',
    failed: 'error',
    skipped: 'wait',
  }
  return map[status] || 'wait'
}

function logClass(log: string) {
  if (log.includes('ERROR') || log.includes('error') || log.includes('失败')) return 'log-error'
  if (log.includes('WARN')) return 'log-warn'
  if (log.includes('SUCCESS') || log.includes('成功')) return 'log-success'
  return ''
}

function formatTime(iso: string) {
  return new Date(iso).toLocaleString('zh-CN')
}

async function fetchRunData() {
  try {
    const { data } = await api.get(`/runs/${runId.value}`)
    runStatus.value = data.status || 'running'
    if (data.node_runs) {
      nodeRuns.value = data.node_runs
    }
  } catch {
    message.error('获取运行数据失败')
  }
}

function cancelRun() {
  api.post(`/runs/${runId.value}/cancel`).then(() => {
    runStatus.value = 'cancelled'
    message.success('运行已取消')
  }).catch(() => message.error('取消失败'))
}

function resumeRun() {
  api.post(`/runs/${runId.value}/resume`).then(() => {
    runStatus.value = 'running'
    message.success('运行已恢复')
  }).catch(() => message.error('恢复失败'))
}

function refreshRun() {
  fetchRunData()
  message.success('已刷新')
}

function connect() {
  if (ws) {
    ws.close()
    ws = null
  }
  try {
    ws = connectWebSocket(runId.value)
    ws.onopen = () => {
      wsConnected.value = true
      reconnectAttempts = 0
      logs.value.push(`[${new Date().toLocaleTimeString()}] [WS] 连接成功`)
      heartbeatTimer = setInterval(() => {
        ws?.send(JSON.stringify({ type: 'ping' }))
      }, 30000)
    }
    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        if (data.type === 'pong') return
        if (data.type === 'node_update') {
          const idx = nodeRuns.value.findIndex(n => n.node_id === data.node_id)
          if (idx >= 0) {
            nodeRuns.value[idx] = { ...nodeRuns.value[idx], ...data.payload }
          } else {
            nodeRuns.value.push(data.payload)
          }
        } else if (data.type === 'status_update') {
          runStatus.value = data.status
        } else if (data.type === 'stream_chunk') {
          const nodeId = data.node_id
          if (!streamChunks.value[nodeId]) {
            streamChunks.value[nodeId] = { chunks: [], ended: false }
          }
          streamChunks.value[nodeId].chunks.push(data.chunk)
          // 实时滚动日志
          logs.value.push(`[STREAM] ${data.tool_name} [${nodeId}]: ${data.chunk}`)
        } else if (data.type === 'stream_end') {
          const nodeId = data.node_id
          if (streamChunks.value[nodeId]) {
            streamChunks.value[nodeId].ended = true
          }
          logs.value.push(`[STREAM] ${data.tool_name} [${nodeId}]: 流式输出完成 (${data.total_chunks} chunks)`)
        } else if (data.type === 'log') {
          logs.value.push(`[${new Date(data.ts || Date.now()).toLocaleTimeString()}] ${data.message}`)
        } else {
          logs.value.push(`[${new Date().toLocaleTimeString()}] ${JSON.stringify(data)}`)
        }
        nextTick(() => {
          if (logContainer.value) {
            logContainer.value.scrollTop = logContainer.value.scrollHeight
          }
        })
      } catch {
        logs.value.push(`[${new Date().toLocaleTimeString()}] ${event.data}`)
      }
    }
    ws.onerror = () => {
      wsConnected.value = false
      logs.value.push(`[${new Date().toLocaleTimeString()}] [WS] 连接错误`)
    }
    ws.onclose = () => {
      wsConnected.value = false
      if (heartbeatTimer) {
        clearInterval(heartbeatTimer)
        heartbeatTimer = null
      }
      if (reconnectAttempts < MAX_RECONNECT && runStatus.value === 'running') {
        reconnectAttempts++
        const delay = Math.min(1000 * Math.pow(2, reconnectAttempts), 30000)
        logs.value.push(`[${new Date().toLocaleTimeString()}] [WS] 断开，${delay / 1000}s后重连 (${reconnectAttempts}/${MAX_RECONNECT})`)
        reconnectTimer = setTimeout(connect, delay)
      }
    }
  } catch (err) {
    message.error('WebSocket连接失败')
  }
}

onMounted(() => {
  fetchRunData()
  connect()
})

onUnmounted(() => {
  if (reconnectTimer) clearTimeout(reconnectTimer)
  if (heartbeatTimer) clearInterval(heartbeatTimer)
  ws?.close()
})

watch(() => runId.value, () => {
  logs.value = []
  fetchRunData()
  connect()
})
</script>

<style scoped>
.log-container {
  background: #1e1e1e;
  color: #d4d4d4;
  padding: 12px;
  border-radius: 4px;
  max-height: 400px;
  overflow-y: auto;
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 12px;
}
.log-container pre {
  margin: 2px 0;
  white-space: pre-wrap;
  word-break: break-word;
}
.log-empty {
  color: #666;
  text-align: center;
  padding: 20px;
}
.log-error {
  color: #ff6b6b;
}
.log-warn {
  color: #ffd93d;
}
.log-success {
  color: #6bcb77;
}
.code-block {
  background: #f5f5f5;
  padding: 8px;
  border-radius: 4px;
  font-size: 11px;
  max-height: 200px;
  overflow: auto;
  margin: 4px 0;
}
.code-block.error {
  background: #fff2f0;
  color: #ff4d4f;
}
.stream-output {
  background: #f0f5ff;
  border: 1px solid #d6e4ff;
  border-radius: 4px;
  padding: 10px;
  margin: 4px 0;
  font-size: 13px;
  line-height: 1.6;
  color: #1d39c4;
  white-space: pre-wrap;
  word-break: break-word;
  min-height: 40px;
  max-height: 300px;
  overflow-y: auto;
}
</style>
