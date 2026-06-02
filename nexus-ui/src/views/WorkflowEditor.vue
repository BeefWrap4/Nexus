<template>
  <div class="workflow-editor-page">
    <!-- 工具栏 -->
    <div class="toolbar">
      <a-space>
        <a-button @click="$router.back()">
          <ArrowLeftOutlined /> 返回
        </a-button>
        <a-divider type="vertical" />
        <a-button type="primary" @click="saveWorkflow">
          <SaveOutlined /> 保存
        </a-button>
        <a-button @click="loadWorkflow">
          <ReloadOutlined /> 加载
        </a-button>
        <a-button @click="exportJson">
          <ExportOutlined /> 导出 JSON
        </a-button>
        <a-upload
          :before-upload="importJson"
          :show-upload-list="false"
          accept=".json"
        >
          <a-button>
            <ImportOutlined /> 导入 JSON
          </a-button>
        </a-upload>
        <a-divider type="vertical" />
        <a-button type="dashed" @click="testWorkflow">
          <PlayCircleOutlined /> 测试运行
        </a-button>
        <a-button danger @click="clearCanvas">
          <ClearOutlined /> 清空画布
        </a-button>
      </a-space>
    </div>

    <!-- 编辑器主体 -->
    <div class="editor-container" @drop="onDrop" @dragover="onDragOver">
      <!-- 左侧节点面板 -->
      <NodePanel />

      <!-- 中间画布区域 -->
      <div class="canvas-area" ref="canvasRef">
        <VueFlow
          v-model="elements"
          :node-types="nodeTypes"
          :default-edge-options="defaultEdgeOptions"
          :default-viewport="{ x: 0, y: 0, zoom: 1 }"
          fit-view-on-init
          @node-click="onNodeClick"
          @pane-click="onPaneClick"
          @connect="onConnect"
          @nodes-change="onNodesChange"
          @edges-change="onEdgesChange"
        >
          <Background pattern-color="#e0e0e0" :gap="16" />
          <Controls />
          <MiniMap />

          <!-- 自定义节点渲染 -->
          <template #node-start="{ id, label, selected }">
            <div class="custom-node node-start" :class="{ selected }">
              <Handle type="source" :position="Position.Bottom" />
              <PlayCircleOutlined class="node-icon" />
              <div class="node-label">{{ label }}</div>
            </div>
          </template>

          <template #node-agent="{ id, label, data, selected }">
            <div class="custom-node node-agent" :class="{ selected }">
              <Handle type="target" :position="Position.Top" />
              <Handle type="source" :position="Position.Bottom" />
              <RobotOutlined class="node-icon" />
              <div class="node-label">{{ label }}</div>
              <div v-if="data?.agent_id" class="node-badge">A</div>
            </div>
          </template>

          <template #node-tool="{ id, label, selected }">
            <div class="custom-node node-tool" :class="{ selected }">
              <Handle type="target" :position="Position.Top" />
              <Handle type="source" :position="Position.Bottom" />
              <ToolOutlined class="node-icon" />
              <div class="node-label">{{ label }}</div>
            </div>
          </template>

          <template #node-hitl="{ id, label, selected }">
            <div class="custom-node node-hitl" :class="{ selected }">
              <Handle type="target" :position="Position.Top" />
              <Handle type="source" :position="Position.Bottom" />
              <PauseCircleOutlined class="node-icon" />
              <div class="node-label">{{ label }}</div>
            </div>
          </template>

          <template #node-condition="{ id, label, selected }">
            <div class="custom-node node-condition" :class="{ selected }">
              <Handle type="target" :position="Position.Top" />
              <Handle type="source" :position="Position.Bottom" id="true" />
              <Handle type="source" :position="Position.Bottom" id="false" style="left: 70%" />
              <QuestionCircleOutlined class="node-icon" />
              <div class="node-label">{{ label }}</div>
            </div>
          </template>

          <template #node-parallel="{ id, label, selected }">
            <div class="custom-node node-parallel" :class="{ selected }">
              <Handle type="target" :position="Position.Top" />
              <Handle type="source" :position="Position.Bottom" />
              <ForkOutlined class="node-icon" />
              <div class="node-label">{{ label }}</div>
            </div>
          </template>

          <template #node-delay="{ id, label, selected }">
            <div class="custom-node node-delay" :class="{ selected }">
              <Handle type="target" :position="Position.Top" />
              <Handle type="source" :position="Position.Bottom" />
              <ClockCircleOutlined class="node-icon" />
              <div class="node-label">{{ label }}</div>
            </div>
          </template>

          <template #node-end="{ id, label, selected }">
            <div class="custom-node node-end" :class="{ selected }">
              <Handle type="target" :position="Position.Top" />
              <CheckCircleOutlined class="node-icon" />
              <div class="node-label">{{ label }}</div>
            </div>
          </template>
        </VueFlow>
      </div>

      <!-- 右侧属性面板 -->
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
        <CopyOutlined /> 复制到剪贴板
      </a-button>
    </a-modal>

    <!-- 测试运行弹窗 -->
    <a-modal
      v-model:open="testModalOpen"
      title="测试运行"
      @ok="confirmTestRun"
      @cancel="testModalOpen = false"
    >
      <a-form layout="vertical">
        <a-form-item label="输入参数 (JSON)">
          <a-textarea
            v-model:value="testInputJson"
            :rows="6"
            placeholder='{"key": "value"}'
          />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { VueFlow, useVueFlow, Handle, Position } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { MiniMap } from '@vue-flow/minimap'
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import { message, Modal } from 'ant-design-vue'
import {
  PlayCircleOutlined,
  RobotOutlined,
  ToolOutlined,
  PauseCircleOutlined,
  QuestionCircleOutlined,
  ForkOutlined,
  ClockCircleOutlined,
  CheckCircleOutlined,
  ArrowLeftOutlined,
  SaveOutlined,
  ReloadOutlined,
  ExportOutlined,
  ImportOutlined,
  ClearOutlined,
  CopyOutlined,
} from '@ant-design/icons-vue'

import NodePanel from '@/components/NodePanel.vue'
import NodeProperties from '@/components/NodeProperties.vue'
import { workflowApi, agentApi, toolApi } from '@/api'
import type { WorkflowNode, Agent, Tool } from '@/types'

const route = useRoute()
const router = useRouter()
const workflowId = computed(() => route.params.id as string)
const isNew = computed(() => workflowId.value === 'new')

const { addEdges, removeNodes, findNode, setNodes, setEdges, fitView } = useVueFlow()

const canvasRef = ref<HTMLElement | null>(null)

// ========== 节点与边 ==========
const nodes = ref<any[]>([
  {
    id: 'start',
    type: 'start',
    label: '开始',
    position: { x: 250, y: 20 },
    data: {},
  },
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
  labelStyle: { fill: '#1677ff', fontSize: 12 },
  type: 'smoothstep',
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

// ========== 选中节点 ==========
const selectedNode = ref<WorkflowNode | null>(null)

// ========== 数据 ==========
const agents = ref<Agent[]>([])
const tools = ref<Tool[]>([])

// ========== 弹窗状态 ==========
const exportModalOpen = ref(false)
const exportedJson = ref('')
const testModalOpen = ref(false)
const testInputJson = ref('{}')

// ========== 生命周期 ==========
onMounted(async () => {
  await fetchAgentsAndTools()
  if (!isNew.value) {
    await loadWorkflowFromServer()
  }
})

async function fetchAgentsAndTools() {
  try {
    const [agentsRes, toolsRes] = await Promise.all([
      agentApi.getList().catch(() => ({ data: [] })),
      toolApi.getList().catch(() => ({ data: [] })),
    ])
    agents.value = agentsRes.data || []
    tools.value = toolsRes.data || []
  } catch {
    // silent fallback
  }
}

async function loadWorkflowFromServer() {
  try {
    const { data } = await workflowApi.getById(workflowId.value)
    if (data.definition) {
      importDefinition(data.definition)
      message.success('工作流加载成功')
    }
  } catch (err: any) {
    message.error(`加载工作流失败: ${err?.response?.data?.detail || err.message}`)
  }
}

// ========== 拖拽放置 ==========
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
    const canvasRect = canvasRef.value?.getBoundingClientRect()
    if (!canvasRect) return

    const position = {
      x: event.clientX - canvasRect.left - 80,
      y: event.clientY - canvasRect.top - 20,
    }

    const id = `${nodeInfo.type}-${Date.now()}`
    const newNode = {
      id,
      type: nodeInfo.type,
      label: nodeInfo.label,
      position,
      data: { type: nodeInfo.type },
    }
    nodes.value.push(newNode)
    message.success(`已添加 ${nodeInfo.label} 节点`)
  } catch {
    message.error('添加节点失败')
  }
}

// ========== 连接 ==========
function onConnect(params: any) {
  addEdges({
    ...params,
    id: `e-${params.source}-${params.target}-${Date.now()}`,
  })
}

// ========== 节点选中/高亮 ==========
function onNodeClick(_event: any, node: any) {
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

// ========== 节点/边变更监听 ==========
function onNodesChange(changes: any[]) {
  for (const change of changes) {
    if (change.type === 'remove') {
      edges.value = edges.value.filter(
        (e: any) => e.source !== change.id && e.target !== change.id
      )
      if (selectedNode.value?.id === change.id) {
        selectedNode.value = null
      }
    }
  }
}

function onEdgesChange(changes: any[]) {
  // 可在此处理边的删除等变更
}

// ========== 节点更新 ==========
function onNodeUpdate(updated: WorkflowNode) {
  const idx = nodes.value.findIndex((n: any) => n.id === updated.id)
  if (idx === -1) return

  const existing = nodes.value[idx]
  nodes.value[idx] = {
    ...existing,
    label: updated.label,
    position: updated.position || existing.position,
    data: {
      ...existing.data,
      config: updated.config,
      agent_id: updated.config?.agent_id,
      tool_id: updated.config?.tool_id,
    },
  }

  // 同步更新选中节点
  selectedNode.value = {
    id: updated.id,
    type: updated.type,
    label: updated.label,
    config: updated.config,
    position: updated.position || existing.position,
  }
}

// ========== 节点删除 ==========
function onNodeDelete(nodeId: string) {
  removeNodes([nodeId])
  nodes.value = nodes.value.filter((n: any) => n.id !== nodeId)
  edges.value = edges.value.filter(
    (e: any) => e.source !== nodeId && e.target !== nodeId
  )
  selectedNode.value = null
  message.success('节点已删除')
}

// ========== 清空画布 ==========
function clearCanvas() {
  Modal.confirm({
    title: '确认清空画布？',
    content: '此操作将删除所有节点和连线，且无法撤销。',
    okText: '确认清空',
    okType: 'danger',
    cancelText: '取消',
    onOk: () => {
      nodes.value = []
      edges.value = []
      selectedNode.value = null
      setNodes([])
      setEdges([])
      message.success('画布已清空')
    },
  })
}

// ========== DAG 序列化/反序列化 ==========
function buildDefinition(): { nodes: any[]; edges: any[] } {
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
      sourceHandle: e.sourceHandle,
      targetHandle: e.targetHandle,
      condition: e.data?.condition,
      label: e.label,
    })),
  }
}

function importDefinition(def: any) {
  if (def.nodes && Array.isArray(def.nodes)) {
    nodes.value = def.nodes.map((n: any) => ({
      id: n.id,
      type: n.type,
      label: n.label,
      position: n.position || { x: 0, y: 0 },
      data: {
        config: n.config || {},
        agent_id: n.config?.agent_id,
        tool_id: n.config?.tool_id,
      },
    }))
  }
  if (def.edges && Array.isArray(def.edges)) {
    edges.value = def.edges.map((e: any) => ({
      id: e.id || `e-${e.source}-${e.target}`,
      source: e.source,
      target: e.target,
      sourceHandle: e.sourceHandle,
      targetHandle: e.targetHandle,
      data: { condition: e.condition },
      label: e.label,
    }))
  }

  // 同步到 VueFlow
  nextTick(() => {
    setNodes([...nodes.value])
    setEdges([...edges.value])
    fitView({ padding: 0.2 })
  })
}

// ========== 保存 ==========
async function saveWorkflow() {
  try {
    const definition = buildDefinition()
    const payload = {
      name: `workflow-${Date.now()}`,
      description: '',
      definition,
    }

    if (!isNew.value) {
      await workflowApi.update(workflowId.value, payload)
      message.success('工作流已更新')
    } else {
      const { data } = await workflowApi.create(payload)
      message.success('工作流已创建')
      // 创建成功后跳转到编辑页面
      if (data.id) {
        router.replace(`/workflows/${data.id}/edit`)
      }
    }

    // 同时保存到 localStorage 作为草稿备份
    localStorage.setItem('nexus_workflow_draft', JSON.stringify(definition))
  } catch (err: any) {
    message.error(`保存失败: ${err?.response?.data?.detail || err.message}`)
  }
}

// ========== 加载 ==========
async function loadWorkflow() {
  if (!isNew.value) {
    await loadWorkflowFromServer()
  } else {
    const saved = localStorage.getItem('nexus_workflow_draft')
    if (saved) {
      try {
        importDefinition(JSON.parse(saved))
        message.success('已从 localStorage 恢复草稿')
      } catch {
        message.error('恢复草稿失败')
      }
    } else {
      message.info('无本地草稿可恢复')
    }
  }
}

// ========== 导出 JSON ==========
function exportJson() {
  const definition = buildDefinition()
  exportedJson.value = JSON.stringify(definition, null, 2)
  exportModalOpen.value = true
}

function copyToClipboard() {
  navigator.clipboard.writeText(exportedJson.value).then(() => {
    message.success('已复制到剪贴板')
  })
}

// ========== 导入 JSON ==========
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

// ========== 测试运行 ==========
function testWorkflow() {
  if (isNew.value) {
    message.warning('请先保存工作流')
    return
  }
  testModalOpen.value = true
}

async function confirmTestRun() {
  try {
    let input = {}
    try {
      input = JSON.parse(testInputJson.value || '{}')
    } catch {
      message.error('输入参数 JSON 格式错误')
      return
    }

    await workflowApi.triggerRun(workflowId.value, input)
    message.success('测试执行已触发')
    testModalOpen.value = false
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
  min-height: 500px;
}

.toolbar {
  padding: 10px 16px;
  border-bottom: 1px solid #d9d9d9;
  background: #fff;
  display: flex;
  align-items: center;
  flex-shrink: 0;
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
  min-width: 0;
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
  transition: box-shadow 0.2s ease, transform 0.15s ease;
  position: relative;
}

.custom-node:hover {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  transform: translateY(-1px);
}

.custom-node.selected {
  box-shadow: 0 0 0 3px rgba(22, 119, 255, 0.3), 0 4px 12px rgba(0, 0, 0, 0.15);
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

/* VueFlow 全局样式覆盖 */
:deep(.vue-flow__node) {
  border: none !important;
  background: transparent !important;
  padding: 0 !important;
}

:deep(.vue-flow__node.selected) {
  box-shadow: none !important;
}

:deep(.vue-flow__edge.selected .vue-flow__edge-path) {
  stroke: #1677ff;
  stroke-width: 3;
}

:deep(.vue-flow__handle) {
  width: 8px;
  height: 8px;
  background: #1677ff;
  border: 2px solid #fff;
}
</style>
