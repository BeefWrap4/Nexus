<template>
  <div class="ai-chat">
    <a-page-header title="AI Assistant" sub-title="Describe your goal and let AI build the workflow">
      <template #extra>
        <a-space>
          <a-tag v-if="lastResult" color="green">Ready</a-tag>
          <a-button @click="clearChat">Clear</a-button>
        </a-space>
      </template>
    </a-page-header>

    <ErrorBoundary>
      <a-row :gutter="24" style="padding: 24px; height: calc(100vh - 140px)">
        <!-- Left: Chat -->
        <a-col :span="10">
          <a-card title="Chat" size="small" style="height: 100%">
            <div class="chat-messages" style="height: calc(100% - 120px); overflow-y: auto; margin-bottom: 16px">
              <a-empty v-if="messages.length === 0" description="Describe your goal to get started" />

              <div v-for="(msg, idx) in messages" :key="idx" :class="['msg', msg.role]"
                   style="margin-bottom: 12px; padding: 8px 12px; border-radius: 8px"
                   :style="{ background: msg.role === 'user' ? '#e6f7ff' : '#f6ffed', textAlign: msg.role === 'user' ? 'right' : 'left' }">
                <div style="font-size: 12px; color: #999; margin-bottom: 4px">{{ msg.role === 'user' ? 'You' : 'NEXUS AI' }}</div>
                <div style="white-space: pre-wrap">{{ msg.content }}</div>
              </div>
              <a-spin v-if="loading" style="display: block; text-align: center; padding: 16px" />
            </div>

            <a-space direction="vertical" style="width: 100%">
              <a-textarea v-model:value="goal" placeholder="e.g. Analyze quarterly sales data, find trends, generate a report and email it..."
                          :rows="3" :disabled="loading" @pressEnter="submitGoal" />
              <a-row justify="end">
                <a-space>
                  <a-button @click="submitGoal" type="primary" :loading="loading" :disabled="!goal.trim()">
                    <template #icon><RocketOutlined /></template>
                    Generate Workflow
                  </a-button>
                </a-space>
              </a-row>
            </a-space>
          </a-card>
        </a-col>

        <!-- Right: Result -->
        <a-col :span="14">
          <a-card title="Generated Workflow" size="small" style="height: 100%">
            <a-empty v-if="!lastResult" description="Your generated DAG will appear here" />

            <a-tabs v-else>
              <a-tab-pane key="dag" tab="DAG Visualization">
                <div class="dag-view" style="background: #fafafa; border-radius: 8px; padding: 16px; min-height: 300px">
                  <div v-for="(node, nIdx) in dagNodes" :key="node.id" style="display: flex; align-items: center; margin-bottom: 8px">
                    <a-tag :color="node.type === 'start' ? 'green' : node.type === 'end' ? 'red' : 'blue'"
                           style="min-width: 80px; text-align: center">
                      {{ node.type.toUpperCase() }}
                    </a-tag>
                    <span style="margin: 0 8px; color: #999">
                      {{ node.id.startsWith('agent_') ? node.config?.agent_ref || node.id : node.id }}
                    </span>
                    <span v-if="nIdx < dagNodes.length - 1" style="color: #1890ff; font-size: 20px">↓</span>
                  </div>
                </div>
              </a-tab-pane>

              <a-tab-pane key="subtasks" tab="Subtasks">
                <a-timeline>
                  <a-timeline-item v-for="task in lastResult.subtasks" :key="task.id"
                    :color="task.depends_on.length ? 'blue' : 'green'">
                    <strong>{{ task.name }}</strong>
                    <p style="color: #666; margin: 4px 0">{{ task.description }}</p>
                    <a-space size="small">
                      <a-tag v-for="dep in task.depends_on" :key="dep" color="orange" size="small">← {{ dep }}</a-tag>
                      <a-tag v-for="tool in task.tool_needs" :key="tool" color="purple" size="small">🔧 {{ tool }}</a-tag>
                    </a-space>
                  </a-timeline-item>
                </a-timeline>
              </a-tab-pane>

              <a-tab-pane key="config" tab="Raw Config">
                <pre style="max-height: 300px; overflow: auto; background: #f5f5f5; padding: 12px; border-radius: 8px; font-size: 11px">{{ JSON.stringify(lastResult.workflow_config, null, 2) }}</pre>
              </a-tab-pane>

              <a-tab-pane key="agents" tab="Agents ({{ lastResult.agent_configs.length }})">
                <a-list size="small" :data-source="lastResult.agent_configs">
                  <template #renderItem="{ item }">
                    <a-list-item>
                      <a-list-item-meta :title="item.name" :description="item.role || item.goal">
                        <template #avatar>
                          <a-avatar style="background-color: #1890ff">{{ (item.name || 'A')[0] }}</a-avatar>
                        </template>
                      </a-list-item-meta>
                    </a-list-item>
                  </template>
                </a-list>
              </a-tab-pane>
            </a-tabs>

            <template v-if="lastResult" #extra>
              <a-space>
                <a-tag color="cyan">{{ lastResult.subtasks?.length || 0 }} subtasks</a-tag>
                <a-tag color="blue">{{ dagNodes.length }} nodes</a-tag>
                <a-button type="primary" size="small" @click="executeWorkflow" :loading="executing">
                  <template #icon><PlayCircleOutlined /></template>
                  Execute
                </a-button>
              </a-space>
            </template>
          </a-card>
        </a-col>
      </a-row>
    </ErrorBoundary>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { message } from 'ant-design-vue'
import { RocketOutlined, PlayCircleOutlined } from '@ant-design/icons-vue'
import ErrorBoundary from '@/components/common/ErrorBoundary.vue'
import { autoApi } from '@/api'

interface Subtask {
  id: string; name: string; description: string
  depends_on: string[]; tool_needs: string[]; agent_role: string
}

interface PlanResult {
  goal: string; subtasks: Subtask[]
  workflow_config: { nodes: any[]; edges: any[] }
  agent_configs: any[]; reasoning: string
}

interface Message {
  role: 'user' | 'assistant'
  content: string
}

const goal = ref('')
const loading = ref(false)
const executing = ref(false)
const messages = ref<Message[]>([])
const lastResult = ref<PlanResult | null>(null)

const dagNodes = computed(() => lastResult.value?.workflow_config?.nodes || [])

async function submitGoal() {
  const text = goal.value.trim()
  if (!text) return

  messages.value.push({ role: 'user', content: text })
  loading.value = true
  goal.value = ''

  try {
    const resp = await autoApi.plan({ goal: text })
    const data = resp.data
    lastResult.value = data

    const summary = [
      `Generated ${data.subtasks.length} subtasks with ${dagNodes.value.length} nodes.`,
      `Reasoning: ${data.reasoning}`,
      `Agents configured: ${data.agent_configs.map((a: any) => a.name).join(', ')}`,
    ].join('\n')

    messages.value.push({ role: 'assistant', content: summary })
    message.success('Workflow generated!')
  } catch (e: any) {
    messages.value.push({ role: 'assistant', content: `Error: ${e.message}` })
    message.error(e.message)
  } finally {
    loading.value = false
  }
}

async function executeWorkflow() {
  const text = lastResult.value?.goal || messages.value.filter(m => m.role === 'user').pop()?.content
  if (!text) return

  executing.value = true
  try {
    const resp = await autoApi.execute({ goal: text })
    const data = resp.data
    if (data.success) {
      message.success(`Workflow executing! Run ID: ${data.run_id?.slice(0, 8)}...`)
      messages.value.push({ role: 'assistant', content: `Execution started: workflow=${data.workflow_id?.slice(0, 8)}..., run=${data.run_id?.slice(0, 8)}...` })
    } else {
      message.error(data.error || 'Execution failed')
    }
  } catch (e: any) {
    message.error(e.message)
  } finally {
    executing.value = false
  }
}

function clearChat() {
  messages.value = []
  lastResult.value = null
  goal.value = ''
}
</script>

<style scoped>
.ai-chat { height: 100%; }
.msg { max-width: 85%; }
.msg.user { margin-left: auto; }
.msg.assistant { margin-right: auto; }
</style>
