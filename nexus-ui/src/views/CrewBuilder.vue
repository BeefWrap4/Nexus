<template>
  <div>
    <a-page-header
      :title="isEdit ? '编辑 Crew' : '创建 Crew'"
      sub-title="配置多 Agent 协作团队"
      @back="() => $router.push('/crews')"
    />

    <a-row :gutter="24" style="margin-top: 16px">
      <!-- 左侧: 基本信息 -->
      <a-col :xs="24" :md="8">
        <a-card title="基本信息" size="small">
          <a-form layout="vertical">
            <a-form-item label="名称" required>
              <a-input v-model:value="form.name" placeholder="如: 研报分析团队" />
            </a-form-item>
            <a-form-item label="描述">
              <a-textarea v-model:value="form.description" :rows="3" placeholder="描述该 Crew 的职责" />
            </a-form-item>
            <a-form-item label="协作模式" required>
              <a-select v-model:value="form.mode">
                <a-select-option value="hierarchical">
                  <ClusterOutlined /> 层级 (Manager-Worker)
                </a-select-option>
                <a-select-option value="sequential">
                  <OrderedListOutlined /> 顺序 (链式传递)
                </a-select-option>
                <a-select-option value="parallel">
                  <ApartmentOutlined /> 并行 (同时执行)
                </a-select-option>
              </a-select>
            </a-form-item>
          </a-form>
        </a-card>

        <a-card title="高级配置" size="small" style="margin-top: 16px">
          <a-form layout="vertical">
            <a-form-item label="最大并发 Worker">
              <a-input-number v-model:value="form.config.max_workers" :min="1" :max="10" style="width: 100%" />
            </a-form-item>
            <a-form-item>
              <a-checkbox v-model:checked="form.config.shared_context_enabled">启用共享上下文</a-checkbox>
            </a-form-item>
            <a-form-item>
              <a-checkbox v-model:checked="form.config.auto_delegate">Manager 自动分解任务</a-checkbox>
            </a-form-item>
          </a-form>
        </a-card>
      </a-col>

      <!-- 中间: Agent Team -->
      <a-col :xs="24" :md="10">
        <a-card title="Agent Team" size="small">
          <template #extra>
            <a-button type="primary" size="small" @click="showAddAgent = true">
              <PlusOutlined /> 添加 Agent
            </a-button>
          </template>

          <a-empty v-if="form.agent_ids.length === 0" description="暂无 Agent，请添加" />

          <a-list v-else size="small" bordered>
            <a-list-item v-for="(item, index) in form.agent_ids" :key="item.agent_id">
              <a-list-item-meta>
                <template #title>
                  <span>{{ getAgentName(item.agent_id) }}</span>
                  <a-tag :color="item.role_in_crew === 'manager' ? 'red' : 'blue'" size="small" style="margin-left: 8px">
                    {{ item.role_in_crew === 'manager' ? 'Manager' : 'Worker' }}
                  </a-tag>
                </template>
                <template #description>
                  顺序: {{ item.order_index }}
                </template>
              </a-list-item-meta>
              <template #actions>
                <a-button type="link" danger size="small" @click="removeAgent(index)">移除</a-button>
              </template>
            </a-list-item>
          </a-list>
        </a-card>
      </a-col>

      <!-- 右侧: 测试运行 -->
      <a-col :xs="24" :md="6">
        <a-card title="测试运行" size="small">
          <a-form layout="vertical">
            <a-form-item label="任务描述">
              <a-textarea v-model:value="testTask" :rows="4" placeholder="输入测试任务..." />
            </a-form-item>
            <a-button type="primary" block :loading="testing" @click="testRun" :disabled="!isEdit">
              <PlayCircleOutlined /> 测试执行
            </a-button>
            <p v-if="!isEdit" style="color: #999; font-size: 12px; margin-top: 8px">
              保存后才能测试运行
            </p>
          </a-form>

          <div v-if="testResult" style="margin-top: 16px">
            <a-divider />
            <h4>执行结果</h4>
            <pre style="background: #f6f6f6; padding: 12px; border-radius: 4px; white-space: pre-wrap; max-height: 300px; overflow: auto; font-size: 12px">
{{ testResult.output }}
            </pre>
          </div>
        </a-card>
      </a-col>
    </a-row>

    <a-affix :offset-bottom="20" style="text-align: center; margin-top: 24px">
      <a-space>
        <a-button @click="$router.push('/crews')">取消</a-button>
        <a-button type="primary" :loading="saving" @click="saveCrew">
          <SaveOutlined /> {{ isEdit ? '保存' : '创建' }}
        </a-button>
      </a-space>
    </a-affix>

    <!-- 添加 Agent Modal -->
    <a-modal v-model:open="showAddAgent" title="选择 Agent" @ok="addAgent">
      <a-form layout="vertical">
        <a-form-item label="Agent" required>
          <a-select v-model:value="selectedAgentId" placeholder="选择 Agent">
            <a-select-option v-for="agent in availableAgents" :key="agent.id" :value="agent.id">
              {{ agent.name }} ({{ agent.role }})
            </a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="角色">
          <a-radio-group v-model:value="selectedRole">
            <a-radio-button value="worker">Worker</a-radio-button>
            <a-radio-button value="manager">Manager</a-radio-button>
          </a-radio-group>
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import {
  PlusOutlined,
  SaveOutlined,
  PlayCircleOutlined,
  ClusterOutlined,
  OrderedListOutlined,
  ApartmentOutlined,
} from '@ant-design/icons-vue'
import api from '@/api'

const route = useRoute()
const router = useRouter()
const crewId = computed(() => route.params.id as string)
const isEdit = computed(() => crewId.value && crewId.value !== 'new')

const saving = ref(false)
const testing = ref(false)
const testTask = ref('')
const testResult = ref<any>(null)
const showAddAgent = ref(false)
const selectedAgentId = ref('')
const selectedRole = ref('worker')
const availableAgents = ref<any[]>([])

const form = reactive({
  name: '',
  description: '',
  mode: 'hierarchical',
  config: {
    max_workers: 5,
    shared_context_enabled: true,
    auto_delegate: true,
  },
  agent_ids: [] as { agent_id: string; role_in_crew: string; order_index: number }[],
})

function getAgentName(agentId: string) {
  const agent = availableAgents.value.find(a => a.id === agentId)
  return agent?.name || agentId
}

function addAgent() {
  if (!selectedAgentId.value) {
    message.warning('请选择 Agent')
    return
  }
  if (form.agent_ids.some(a => a.agent_id === selectedAgentId.value)) {
    message.warning('该 Agent 已添加')
    return
  }
  form.agent_ids.push({
    agent_id: selectedAgentId.value,
    role_in_crew: selectedRole.value,
    order_index: form.agent_ids.length,
  })
  selectedAgentId.value = ''
  selectedRole.value = 'worker'
  showAddAgent.value = false
}

function removeAgent(index: number) {
  form.agent_ids.splice(index, 1)
  // 重新计算 order_index
  form.agent_ids.forEach((a, i) => {
    a.order_index = i
  })
}

async function fetchAgents() {
  try {
    const resp = await api.get('/agents')
    availableAgents.value = resp.data || []
  } catch {
    availableAgents.value = []
  }
}

async function fetchCrew() {
  if (!isEdit.value) return
  try {
    const resp = await api.get(`/crews/${crewId.value}`)
    form.name = resp.data.name
    form.description = resp.data.description
    form.mode = data.mode
    form.config = { ...form.config, ...data.config }
    form.agent_ids = data.agents?.map((a: any) => ({
      agent_id: a.id,
      role_in_crew: a.role_in_crew,
      order_index: a.order_index,
    })) || []
  } catch {
    message.error('获取 Crew 详情失败')
  }
}

async function saveCrew() {
  if (!form.name) {
    message.warning('请输入 Crew 名称')
    return
  }
  if (form.agent_ids.length === 0) {
    message.warning('请至少添加一个 Agent')
    return
  }

  saving.value = true
  try {
    const payload = {
      name: form.name,
      description: form.description,
      mode: form.mode,
      config: form.config,
      agent_ids: form.agent_ids,
    }
    if (isEdit.value) {
      await api.put(`/crews/${crewId.value}`, payload)
      message.success('Crew 已更新')
    } else {
      const resp = await api.post('/crews', payload)
      message.success('Crew 已创建')
      router.push(`/crews/${data.id}/edit`)
    }
  } catch (e: any) {
    message.error(e.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

async function testRun() {
  if (!testTask.value.trim()) {
    message.warning('请输入任务描述')
    return
  }
  testing.value = true
  testResult.value = null
  try {
    const resp = await api.post(`/crews/${crewId.value}/run`, {
      task_description: testTask.value,
    })
    testResult.value = data
    message.success('测试执行完成')
  } catch (e: any) {
    message.error(e.response?.data?.detail || '执行失败')
  } finally {
    testing.value = false
  }
}

onMounted(() => {
  fetchAgents()
  fetchCrew()
})
</script>
