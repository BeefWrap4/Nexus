<template>
  <div class="workflow-editor-page">
    <a-space class="toolbar">
      <a-button @click="$router.back()">返回</a-button>
      <a-button type="primary" @click="saveWorkflow">保存</a-button>
      <a-button @click="loadWorkflow">加载</a-button>
      <a-button @click="exportJson">导出 JSON</a-button>
      <a-upload
        :before-upload="importJson"
        :show-upload-list="false"
        accept=".json"
      >
        <a-button>导入 JSON</a-button>
      </a-upload>
      <a-button type="dashed" @click="testWorkflow">测试执行</a-button>
    </a-space>

    <div class="editor-container" @drop="onDrop" @dragover="onDragOver">
      <NodePanel />

      <div class="canvas-area">
        <VueFlow
          v-model="elements"
          :node-types="nodeTypes"
          :default-edge-options="defaultEdgeOptions"
          fit-view-on-init
          @node-click="onNodeClick"
          @pane-click="onPaneClick"
          @connect="onConnect"
        >
          <Background />
          <Controls />
          <MiniMap />

          <!-- 自定义节点渲染 -->
          <template #node-start="{ label }">
            <div class="custom-node node-start">
              <PlayCircleOutlined class="node-icon" />
              <div class="node-label">{{ label }}</div>
            </div>
          </template>

          <template #node-agent="{ data, label }">
            <div class="custom-node node-agent">
              <RobotOutlined class="node-icon" />
              <div class="node-label">{{ label }}</div>
              <div v-if="data?.agent_id" class="node-badge">A</div>
            </div>
          </template>

          <template #node-tool="{ label }">
            <div class="custom-node node-tool">
              <ToolOutlined class="node-icon" />
              <div class="node-label">{{ label }}</div>
            </div>
          </template>

          <template #node-hitl="{ label }">
            <div class="custom-node node-hitl">
              <PauseCircleOutlined class="node-icon" />
              <div class="node-label">{{ label }}</div>
            </div>
          </template>

          <template #node-condition="{ label }">
            <div class="custom-node node-condition">
              <QuestionCircleOutlined class="node-icon" />
              <div class="node-label">{{ label }}</div>
            </div>
          </template>

          <template #node-parallel="{ label }">
            <div class="custom-node node-parallel">
              <ForkOutlined class="node-icon" />
              <div class="node-label">{{ label }}</div>
            </div>
          </template>

          <template #node-delay="{ label }">
            <div class="custom-node node-delay">
              <ClockCircleOutlined class="node-icon" />
              <div class="node-label">{{ label }}</div>
            </div>
          </template>

          <template #node-end="{ label }">
            <div class="custom-node node-end">
              <CheckCircleOutlined class="node-icon" />
              <div class="node-label">{{ label }}</div>
            </div>
          </template>
        </VueFlow>
      </div>

      <NodeProperties
        :node="selectedNode"
        :agents="agents"
        :tools="tools"
        @update="onNodeUpdate"
        @delete="onNodeDelete"
      />
    </div>

    <!-- 导出 JSON 弹窗 -->
    <a-modal
      v-model:open="exportModalOpen"
      title="工作流 JSON"
      width="800px"
      :footer="null"
    >
      <a-textarea
        :value="exportedJson"
        :rows="16"
        readonly
      />
      <a-button
        type="primary"
        style="margin-top: 12px"
        @click="copyToClipboard"
      >
        复制到剪贴板
      </a-button>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { VueFlow, useVueFlow } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { MiniMap } from '@vue-flow/minimap'
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import { message } from 'ant-design-vue'
import {
  PlayCircleOutlined,
  RobotOutlined,
  ToolOutlined,
  PauseCircleOutlined,
  QuestionCircleOutlined,
  ForkOutlined,
  ClockCircleOutlined,
  CheckCircleOutlined,
} from '@ant-design/icons-vue'

import NodePanel from '@/components/NodePanel.vue'
import NodeProperties from '@/components/NodeProperties.vue'
import api from '@/api'
import type { WorkflowNode, Agent, Tool } from '@/types'

const route = useRoute()
const workflowId = computed(() => route.params.id as string)

const { addEdges, removeNodes } = useVueFlow()

// 节点与边
const nodes = ref<any[]>([
  { id: 'start', type: 'start', label: '开始', position: { x: 250, y: 20 }, data: {} },
])
const edges = ref<any[]>([])
const elements = computed({
  get: () => [...nodes.value, ...edges.value],
  set: (val: any[]) => {
    nodes.value = val.filter((item) => !item.source)
    edges.value = val.filter((item) => item.source)
  },
})

const defaultEdgeOptions = {
  animated: true,
  style: { stroke: '#1677ff', strokeWidth: 2 },
}

const nodeTypes = {
  start: 'start',
  agent: 'agent',
  tool: 'tool',
  hitl: 'hitl',
  condition: 'condition',
  parallel: 'parallel',
  delay: 'delay',
  end: 'end',
}

// 选中节点
const selectedNode = ref<WorkflowNode | null>(null)

// 数据
const agents = ref<Agent[]>([])
const tools = ref<Tool[]>([])

// 导出弹窗
const exportModalOpen = ref(false)
const exportedJson = ref('')

onMounted(async () => {
  await fetchAgentsAndTools()
  if (workflowId.value && workflowId.value !== 'new') {
    await loadWorkflowFromServer()
  }
})

async function fetchAgentsAndTools() {
  try {
    const [agentsRes, toolsRes] = await Promise.all([
      api.get('/agents').catch(() => ({ data: [] })),
      api.get('/tools').catch(() => ({ data: [] })),
    ])
    agents.value = agentsRes.data || []
    tools.value = toolsRes.data || []
  } catch (err) {
    // silent fallback
  }
}

async function loadWorkflowFromServer() {
  try {
    const { data } = await api.get(`/workflows/${workflowId.value}`)
    if (data.definition) {
      importDefinition(data.definition)
    }
  } catch (err: any) {
    message.error(`加载工作流失败: ${err?.response?.data?.detail || err.message}`)
  }
}

// 拖拽放置
function onDragOver(event: DragEvent) {
  event.preventDefault()
  if (event.dataTransfer) {
    event.dataTransfer.dropEffect = 'move'
  }
}

function onDrop(event: DragEvent) {
  event.preventDefault()
  const transferData = event.dataTransfer?.getData('application/vueflow')
  if (!transferData) return

  try {
    const nodeInfo = JSON.parse(transferData)
    const { left, top } = (event.currentTarget as HTMLElement).getBoundingClientRect()
    const position = {
      x: event.clientX - left - 80,
      y: event.clientY - top - 20,
    }
    const id = `${nodeInfo.type}-${Date.now()}`
    const newNode = {
      id,
      type: nodeInfo.type,
      label: nodeInfo.label,
      position,
      data: { type: nodeInfo.type },
    } as any
    nodes.value.push(newNode)
    message.success(`已添加 ${nodeInfo.label} 节点`)
  } catch {
    message.error('添加节点失败')
  }
}

// 连接
function onConnect(params: any) {
  addEdges(params)
}

// 节点点击
function onNodeClick(event: any) {
  const node = event.node
  const found = nodes.value.find((n: any) => n.id === node.id)
  if (!found) return
  selectedNode.value = {
    id: found.id,
    type: found.type as WorkflowNode['type'],
    label: (found.label as string) || found.type || '',
    config: (found.data?.config as Record<string, any>) || {},
    position: found.position,
  }
}

function onPaneClick() {
  selectedNode.value = null
}

// 节点更新
function onNodeUpdate(updated: WorkflowNode) {
  const idx = nodes.value.findIndex((n: any) => n.id === updated.id)
  if (idx === -1) return
  const existing = nodes.value[idx] as any
  nodes.value[idx] = {
    ...existing,
    label: updated.label,
    position: updated.position || { x: 0, y: 0 },
    data: {
      ...existing.data,
      config: updated.config,
      agent_id: updated.config?.agent_id,
      tool_id: updated.config?.tool_id,
    },
  } as any
}

// 节点删除
function onNodeDelete(nodeId: string) {
  removeNodes([nodeId])
  nodes.value = nodes.value.filter((n: any) => n.id !== nodeId)
  edges.value = edges.value.filter((e: any) => e.source !== nodeId && e.target !== nodeId)
  selectedNode.value = null
  message.success('节点已删除')
}

// 保存 / 加载
function buildDefinition() {
  return {
    nodes: nodes.value.map((n) => ({
      id: n.id,
      type: n.type,
      label: n.label,
      position: n.position,
      config: n.data?.config || {},
    })),
    edges: edges.value.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      condition: e.data?.condition,
    })),
  }
}

function importDefinition(def: any) {
  if (def.nodes) {
    nodes.value = def.nodes.map((n: any) => ({
      id: n.id,
      type: n.type,
      label: n.label,
      position: n.position || { x: 0, y: 0 },
      data: { config: n.config || {}, agent_id: n.config?.agent_id, tool_id: n.config?.tool_id },
    }))
  }
  if (def.edges) {
    edges.value = def.edges.map((e: any) => ({
      id: e.id || `e-${e.source}-${e.target}`,
      source: e.source,
      target: e.target,
      data: { condition: e.condition },
    }))
  }
}

async function saveWorkflow() {
  try {
    const definition = buildDefinition()
    if (workflowId.value && workflowId.value !== 'new') {
      await api.put(`/workflows/${workflowId.value}`, { definition })
      message.success('工作流已更新')
    } else {
      await api.post('/workflows', { definition })
      message.success('工作流已创建')
    }
  } catch (err: any) {
    message.error(`保存失败: ${err?.response?.data?.detail || err.message}`)
  }
}

async function loadWorkflow() {
  if (workflowId.value && workflowId.value !== 'new') {
    await loadWorkflowFromServer()
  } else {
    message.info('无服务端工作流可加载，尝试从 localStorage 恢复')
    const saved = localStorage.getItem('nexus_workflow_draft')
    if (saved) {
      try {
        importDefinition(JSON.parse(saved))
        message.success('已从 localStorage 恢复草稿')
      } catch {
        message.error('恢复草稿失败')
      }
    }
  }
}

function exportJson() {
  const definition = buildDefinition()
  exportedJson.value = JSON.stringify(definition, null, 2)
  exportModalOpen.value = true
}

function importJson(file: File) {
  const reader = new FileReader()
  reader.onload = (e) => {
    try {
      const def = JSON.parse(e.target?.result as string)
      importDefinition(def)
      message.success('工作流导入成功')
    } catch {
      message.error('JSON 解析失败')
    }
  }
  reader.readAsText(file)
  return false
}

function copyToClipboard() {
  navigator.clipboard.writeText(exportedJson.value).then(() => {
    message.success('已复制')
  })
}

async function testWorkflow() {
  try {
    if (workflowId.value && workflowId.value !== 'new') {
      await api.post(`/workflows/${workflowId.value}/runs`, {})
      message.success('测试执行已触发')
    } else {
      message.warning('请先保存工作流')
    }
  } catch (err: any) {
    message.error(`测试执行失败: ${err?.response?.data?.detail || err.message}`)
  }
}
</script>

<style scoped>
.workflow-editor-page {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 140px);
}
.toolbar {
  padding: 8px 12px;
  border-bottom: 1px solid #d9d9d9;
  background: #fff;
}
.editor-container {
  display: flex;
  flex: 1;
  overflow: hidden;
}
.canvas-area {
  flex: 1;
  position: relative;
  height: 100%;
}

/* 自定义节点样式 */
.custom-node {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  border-radius: 8px;
  background: #fff;
  border: 2px solid;
  min-width: 120px;
  font-size: 13px;
  font-weight: 500;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.08);
}
.node-icon {
  font-size: 18px;
}
.node-label {
  white-space: nowrap;
}
.node-badge {
  position: absolute;
  top: -6px;
  right: -6px;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: #1677ff;
  color: #fff;
  font-size: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.node-start { border-color: #52c41a; color: #52c41a; }
.node-agent { border-color: #1677ff; color: #1677ff; position: relative; }
.node-tool { border-color: #722ed1; color: #722ed1; }
.node-hitl { border-color: #fa8c16; color: #fa8c16; }
.node-condition { border-color: #eb2f96; color: #eb2f96; }
.node-parallel { border-color: #13c2c2; color: #13c2c2; }
.node-delay { border-color: #8c8c8c; color: #8c8c8c; }
.node-end { border-color: #f5222d; color: #f5222d; }
</style>
