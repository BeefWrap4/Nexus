<template>
  <div class="properties-panel">
    <h4 class="panel-title">
      <EditOutlined /> 属性面板
    </h4>

    <div v-if="!node" class="empty-state">
      <InfoCircleOutlined class="empty-icon" />
      <p>选中节点查看属性</p>
    </div>

    <a-form v-else layout="vertical" class="prop-form">
      <!-- 通用字段 -->
      <a-form-item label="节点 ID">
        <a-input v-model:value="localNode.id" disabled />
      </a-form-item>

      <a-form-item label="节点类型">
        <a-tag :color="typeColor">{{ typeLabel }}</a-tag>
      </a-form-item>

      <a-form-item label="显示名称">
        <a-input
          v-model:value="localNode.label"
          placeholder="输入节点名称"
          @change="emitUpdate"
        />
      </a-form-item>

      <!-- 各类型特有配置 -->
      <template v-if="node.type === 'agent'">
        <a-form-item label="选择 Agent">
          <a-select
            v-model:value="localNode.config.agent_id"
            placeholder="选择 Agent"
            @change="emitUpdate"
          >
            <a-select-option
              v-for="agent in agents"
              :key="agent.id"
              :value="agent.id"
            >
              {{ agent.name }} ({{ agent.role }})
            </a-select-option>
          </a-select>
        </a-form-item>

        <a-form-item label="系统提示词">
          <a-textarea
            v-model:value="localNode.config.system_prompt"
            :rows="3"
            placeholder="输入系统提示词..."
            @change="emitUpdate"
          />
        </a-form-item>

        <a-form-item label="最大重试次数">
          <a-input-number
            v-model:value="localNode.config.max_retries"
            :min="0"
            :max="5"
            style="width: 100%"
            @change="emitUpdate"
          />
        </a-form-item>
      </template>

      <template v-if="node.type === 'tool'">
        <a-form-item label="选择工具">
          <a-select
            v-model:value="localNode.config.tool_name"
            placeholder="选择工具"
            @change="onToolChange"
          >
            <a-select-option
              v-for="tool in tools"
              :key="tool.id"
              :value="tool.name"
            >
              <span>{{ tool.name }}</span>
              <a-tag v-if="tool.source === 'registry'" size="small" color="purple" style="margin-left: 6px">RAG</a-tag>
              <span v-if="tool.description" style="margin-left: 6px; color: #999; font-size: 12px">
                {{ tool.description.slice(0, 30) }}
              </span>
            </a-select-option>
          </a-select>
        </a-form-item>

        <!-- 动态参数表单（基于 JSON Schema） -->
        <template v-if="selectedToolSchema">
          <a-divider style="margin: 8px 0">
            <span style="font-size: 12px; color: #999">参数配置</span>
          </a-divider>

          <div
            v-for="(propDef, propName) in selectedToolSchema.properties"
            :key="propName"
          >
            <a-form-item :label="propName">
              <template #help>
                <span style="color: #999">{{ propDef.description }}</span>
              </template>

              <!-- string 类型 -->
              <a-input
                v-if="propDef.type === 'string'"
                v-model:value="toolParamValues[propName]"
                :placeholder="propDef.default ?? getPlaceholder(String(propName))"
                @change="emitToolParamsUpdate"
              />

              <!-- number 类型 -->
              <a-input-number
                v-else-if="propDef.type === 'number'"
                v-model:value="toolParamValues[propName]"
                :placeholder="propDef.default"
                style="width: 100%"
                @change="emitToolParamsUpdate"
              />

              <!-- integer 类型 -->
              <a-input-number
                v-else-if="propDef.type === 'integer'"
                v-model:value="toolParamValues[propName]"
                :placeholder="propDef.default"
                :precision="0"
                style="width: 100%"
                @change="emitToolParamsUpdate"
              />

              <!-- boolean 类型 -->
              <a-switch
                v-else-if="propDef.type === 'boolean'"
                v-model:checked="toolParamValues[propName]"
                @change="emitToolParamsUpdate"
              />

              <!-- 其他类型：JSON 输入 -->
              <a-input
                v-else
                v-model:value="toolParamValues[propName]"
                :placeholder="getPlaceholder(String(propName))"
                @change="emitToolParamsUpdate"
              />
            </a-form-item>
          </div>
        </template>

        <!-- 无 Schema 时回退到 JSON 文本框 -->
        <template v-else>
          <a-form-item label="工具参数 (JSON)">
            <a-textarea
              v-model:value="toolParamsJson"
              :rows="4"
              placeholder='{"key": "value"} — 支持变量模板 {{#trigger.field#}}'
              @blur="updateToolParams"
            />
          </a-form-item>
        </template>
      </template>

      <template v-if="node.type === 'condition'">
        <a-form-item label="条件表达式">
          <a-textarea
            v-model:value="localNode.config.expression"
            :rows="2"
            placeholder="如: input.score > 0.8"
            @change="emitUpdate"
          />
        </a-form-item>

        <a-form-item label="真分支标签">
          <a-input
            v-model:value="localNode.config.true_label"
            placeholder="True"
            @change="emitUpdate"
          />
        </a-form-item>

        <a-form-item label="假分支标签">
          <a-input
            v-model:value="localNode.config.false_label"
            placeholder="False"
            @change="emitUpdate"
          />
        </a-form-item>
      </template>

      <template v-if="node.type === 'hitl'">
        <a-form-item label="任务类型">
          <a-select
            v-model:value="localNode.config.task_type"
            placeholder="选择任务类型"
            @change="emitUpdate"
          >
            <a-select-option value="approve">审批</a-select-option>
            <a-select-option value="select">选择</a-select-option>
            <a-select-option value="input">输入</a-select-option>
            <a-select-option value="correct">修正</a-select-option>
          </a-select>
        </a-form-item>

        <a-form-item label="任务标题">
          <a-input
            v-model:value="localNode.config.title"
            placeholder="输入任务标题"
            @change="emitUpdate"
          />
        </a-form-item>

        <a-form-item label="超时时间 (秒)">
          <a-input-number
            v-model:value="localNode.config.timeout"
            :min="10"
            :max="86400"
            style="width: 100%"
            @change="emitUpdate"
          />
        </a-form-item>

        <a-form-item label="超时处理">
          <a-radio-group
            v-model:value="localNode.config.timeout_action"
            @change="emitUpdate"
          >
            <a-radio value="fail">失败</a-radio>
            <a-radio value="continue">继续</a-radio>
          </a-radio-group>
        </a-form-item>
      </template>

      <template v-if="node.type === 'delay'">
        <a-form-item label="延迟时长 (秒)">
          <a-input-number
            v-model:value="localNode.config.duration"
            :min="1"
            :max="86400"
            style="width: 100%"
            @change="emitUpdate"
          />
        </a-form-item>
      </template>

      <template v-if="node.type === 'parallel'">
        <a-form-item label="聚合策略">
          <a-select
            v-model:value="localNode.config.aggregate"
            @change="emitUpdate"
          >
            <a-select-option value="all">全部完成</a-select-option>
            <a-select-option value="any">任一完成</a-select-option>
            <a-select-option value="first">首个完成</a-select-option>
          </a-select>
        </a-form-item>
      </template>

      <a-divider />

      <a-form-item label="位置 X">
        <a-input-number
          :value="localNode.position?.x"
          style="width: 100%"
          disabled
        />
      </a-form-item>

      <a-form-item label="位置 Y">
        <a-input-number
          :value="localNode.position?.y"
          style="width: 100%"
          disabled
        />
      </a-form-item>

      <a-button
        danger
        block
        style="margin-top: 8px"
        @click="emitDelete"
      >
        <DeleteOutlined /> 删除节点
      </a-button>
    </a-form>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, computed, reactive } from 'vue'
import {
  EditOutlined,
  InfoCircleOutlined,
  DeleteOutlined,
} from '@ant-design/icons-vue'
import type { WorkflowNode } from '@/types'
import type { Agent, Tool } from '@/types'

interface Props {
  node: WorkflowNode | null
  agents?: Agent[]
  tools?: Tool[]
}

const props = withDefaults(defineProps<Props>(), {
  agents: () => [],
  tools: () => [],
})

const emit = defineEmits<{
  (e: 'update', node: WorkflowNode): void
  (e: 'delete', nodeId: string): void
}>()

const localNode = ref<WorkflowNode>({
  id: '',
  type: 'agent',
  label: '',
  config: {},
  position: { x: 0, y: 0 },
})

const toolParamsJson = ref('')
const toolParamValues = reactive<Record<string, any>>({})

const typeLabelMap: Record<string, string> = {
  start: '开始',
  agent: 'Agent',
  tool: '工具',
  hitl: '人工审核',
  condition: '条件分支',
  parallel: '并行',
  loop: '循环',
  delay: '延迟',
  end: '结束',
}

const typeColorMap: Record<string, string> = {
  start: 'green',
  agent: 'blue',
  tool: 'purple',
  hitl: 'orange',
  condition: 'pink',
  parallel: 'cyan',
  loop: 'geekblue',
  delay: 'default',
  end: 'red',
}

const typeLabel = computed(() => (props.node ? typeLabelMap[props.node.type] || props.node.type : ''))
const typeColor = computed(() => (props.node ? typeColorMap[props.node.type] || 'default' : 'default'))

// 当前选中的工具定义
const selectedTool = computed(() => {
  const name = localNode.value.config?.tool_name
  if (!name) return null
  return props.tools.find((t) => t.name === name) || null
})

// 当前选中工具的 JSON Schema
const selectedToolSchema = computed(() => {
  return selectedTool.value?.schema || null
})

watch(
  () => props.node,
  (newNode) => {
    if (newNode) {
      localNode.value = JSON.parse(JSON.stringify(newNode))
      if (newNode.type === 'tool') {
        // 初始化工具参数
        const existingParams = newNode.config.inputs || newNode.config.params || {}
        if (newNode.config.tool_name && selectedToolSchema.value) {
          // Schema 模式：初始化参数值
          const schema = selectedToolSchema.value
          const props_def = schema.properties || {}
          Object.keys(toolParamValues).forEach((k) => delete toolParamValues[k])
          for (const [key, def] of Object.entries(props_def)) {
            toolParamValues[key] = existingParams[key] ?? (def as any).default ?? ''
          }
          toolParamsJson.value = JSON.stringify(existingParams, null, 2)
        } else {
          // JSON 模式
          toolParamsJson.value = JSON.stringify(existingParams, null, 2)
        }
      }
    }
  },
  { immediate: true, deep: true }
)

function onToolChange() {
  // 切换工具时重置参数
  Object.keys(toolParamValues).forEach((k) => delete toolParamValues[k])
  const schema = selectedToolSchema.value
  if (schema?.properties) {
    for (const [key, def] of Object.entries(schema.properties)) {
      toolParamValues[key] = (def as any).default ?? ''
    }
    localNode.value.config.inputs = { ...toolParamValues }
  }
  emitUpdate()
}

function emitToolParamsUpdate() {
  // 将动态表单的值同步到 config.inputs（WorkflowEngine 通过 VariablePool 解析）
  localNode.value.config.inputs = { ...toolParamValues }
  // 同时更新 tool_name 以确保兼容性
  localNode.value.config.tool_name = selectedTool.value?.name || localNode.value.config.tool_name
  emitUpdate()
}

function getPlaceholder(propName: string): string {
  return `支持变量模板 {{#trigger.${propName}#}}`
}

function emitUpdate() {
  emit('update', JSON.parse(JSON.stringify(localNode.value)))
}

function updateToolParams() {
  try {
    const parsed = JSON.parse(toolParamsJson.value || '{}')
    localNode.value.config.inputs = parsed
    emitUpdate()
  } catch (err) {
    // ignore JSON parse error on blur; user can fix it
  }
}

function emitDelete() {
  if (localNode.value.id) {
    emit('delete', localNode.value.id)
  }
}
</script>

<style scoped>
.properties-panel {
  width: 300px;
  height: 100%;
  padding: 12px;
  border-left: 1px solid #d9d9d9;
  background: #fafafa;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.panel-title {
  margin: 0 0 12px 0;
  font-size: 14px;
  font-weight: 600;
  color: #262626;
  display: flex;
  align-items: center;
  gap: 6px;
}
.empty-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #bfbfbf;
}
.empty-icon {
  font-size: 32px;
  margin-bottom: 8px;
}
.prop-form {
  flex: 1;
  overflow-y: auto;
}
</style>
