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
            v-model:value="localNode.config.tool_id"
            placeholder="选择工具"
            @change="emitUpdate"
          >
            <a-select-option
              v-for="tool in tools"
              :key="tool.id"
              :value="tool.id"
            >
              {{ tool.name }}
            </a-select-option>
          </a-select>
        </a-form-item>

        <a-form-item label="工具参数 (JSON)">
          <a-textarea
            v-model:value="toolParamsJson"
            :rows="4"
            placeholder='{"key": "value"}'
            @blur="updateToolParams"
          />
        </a-form-item>
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
import { ref, watch, computed } from 'vue'
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

watch(
  () => props.node,
  (newNode) => {
    if (newNode) {
      localNode.value = JSON.parse(JSON.stringify(newNode))
      if (newNode.type === 'tool' && newNode.config.params) {
        toolParamsJson.value = JSON.stringify(newNode.config.params, null, 2)
      } else {
        toolParamsJson.value = '{}'
      }
    }
  },
  { immediate: true, deep: true }
)

function emitUpdate() {
  emit('update', JSON.parse(JSON.stringify(localNode.value)))
}

function updateToolParams() {
  try {
    const parsed = JSON.parse(toolParamsJson.value || '{}')
    localNode.value.config.params = parsed
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
