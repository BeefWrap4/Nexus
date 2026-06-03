<template>
  <div>
    <a-page-header title="Crew 团队" sub-title="多 Agent 协作编排">
      <template #extra>
        <a-button type="primary" @click="$router.push('/crews/new')">
          <PlusOutlined /> 创建 Crew
        </a-button>
      </template>
    </a-page-header>

    <a-row :gutter="16" style="margin-top: 16px">
      <a-col v-for="crew in crews" :key="crew.id" :xs="24" :sm="12" :md="8" :lg="6" style="margin-bottom: 16px">
        <a-card hoverable size="small">
          <template #title>
            <div style="display: flex; justify-content: space-between; align-items: center">
              <span><TeamOutlined /> {{ crew.name }}</span>
              <a-dropdown>
                <a-button type="text" size="small"><EllipsisOutlined /></a-button>
                <template #overlay>
                  <a-menu>
                    <a-menu-item key="edit" @click="$router.push(`/crews/${crew.id}/edit`)">编辑</a-menu-item>
                    <a-menu-item key="run" @click="openRunModal(crew)">执行</a-menu-item>
                    <a-menu-item key="delete" danger @click="deleteCrew(crew.id)">删除</a-menu-item>
                  </a-menu>
                </template>
              </a-dropdown>
            </div>
          </template>
          <p style="color: #666; font-size: 12px; margin: 0"><strong>模式:</strong>
            <a-tag :color="modeColor(crew.mode)">{{ modeLabel(crew.mode) }}</a-tag>
          </p>
          <p style="color: #666; font-size: 12px; margin: 4px 0 0"><strong>Agent 数:</strong> {{ crew.agents?.length || 0 }}</p>
          <p style="color: #999; font-size: 11px; margin: 8px 0 0">{{ crew.description || '无描述' }}</p>
        </a-card>
      </a-col>
    </a-row>

    <!-- Run Modal -->
    <a-modal v-model:open="runModalOpen" title="执行 Crew" @ok="runCrew" :confirm-loading="running">
      <a-form layout="vertical">
        <a-form-item label="任务描述" required>
          <a-textarea v-model:value="runTask" :rows="4" placeholder="输入需要 Crew 协作完成的任务..." />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import { PlusOutlined, TeamOutlined, EllipsisOutlined } from '@ant-design/icons-vue'
import api from '@/api'

interface Crew {
  id: string
  name: string
  description: string
  mode: string
  agents: any[]
}

const crews = ref<Crew[]>([])
const loading = ref(false)
const runModalOpen = ref(false)
const running = ref(false)
const runTask = ref('')
const runningCrewId = ref('')

function modeLabel(mode: string) {
  const labels: Record<string, string> = {
    hierarchical: '层级',
    sequential: '顺序',
    parallel: '并行',
  }
  return labels[mode] || mode
}

function modeColor(mode: string) {
  const colors: Record<string, string> = {
    hierarchical: 'blue',
    sequential: 'green',
    parallel: 'purple',
  }
  return colors[mode] || 'default'
}

async function fetchCrews() {
  loading.value = true
  try {
    const { data } = await api.get('/crews')
    crews.value = data || []
  } catch {
    message.error('获取 Crew 列表失败')
    crews.value = []
  } finally {
    loading.value = false
  }
}

function openRunModal(crew: Crew) {
  runningCrewId.value = crew.id
  runTask.value = ''
  runModalOpen.value = true
}

async function runCrew() {
  if (!runTask.value.trim()) {
    message.warning('请输入任务描述')
    return
  }
  running.value = true
  try {
    const { data } = await api.post(`/crews/${runningCrewId.value}/run`, {
      task_description: runTask.value,
    })
    message.success('Crew 执行完成')
    runModalOpen.value = false
    console.log('Crew run result:', data)
  } catch (e: any) {
    message.error(e.response?.data?.detail || '执行失败')
  } finally {
    running.value = false
  }
}

async function deleteCrew(id: string) {
  try {
    await api.delete(`/crews/${id}`)
    message.success('Crew 已删除')
    await fetchCrews()
  } catch {
    message.error('删除失败')
  }
}

onMounted(fetchCrews)
</script>
