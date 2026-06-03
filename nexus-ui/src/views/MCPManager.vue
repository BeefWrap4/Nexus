<template>
  <div>
    <a-page-header title="MCP 管理" sub-title="Model Context Protocol Server 连接管理">
      <template #extra>
        <a-button type="primary" @click="showAddModal = true">
          <PlusOutlined /> 添加连接
        </a-button>
      </template>
    </a-page-header>

    <!-- Connection List -->
    <a-table
      :columns="columns"
      :data-source="connections"
      :loading="loading"
      row-key="name"
      style="margin-top: 16px"
    >
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'status'">
          <a-tag :color="record.connected ? 'green' : 'red'">
            {{ record.connected ? '已连接' : '未连接' }}
          </a-tag>
        </template>
        <template v-if="column.key === 'tools'">
          <a-space>
            <a-tag v-for="tool in record.tools" :key="tool" color="blue">
              {{ tool }}
            </a-tag>
            <span v-if="!record.tools?.length" style="color: #999">—</span>
          </a-space>
        </template>
        <template v-if="column.key === 'action'">
          <a-button type="link" danger @click="disconnect(record.name)">
            <DisconnectOutlined /> 断开
          </a-button>
        </template>
      </template>
    </a-table>

    <!-- Add Connection Modal -->
    <a-modal
      v-model:open="showAddModal"
      title="添加 MCP Server 连接"
      @ok="handleAddConnection"
      :confirm-loading="addLoading"
    >
      <a-form :model="form" layout="vertical">
        <a-form-item label="连接名称" required>
          <a-input v-model:value="form.name" placeholder="如：filesystem" />
        </a-form-item>
        <a-form-item label="传输类型" required>
          <a-select v-model:value="form.transport">
            <a-select-option value="stdio">stdio（本地进程）</a-select-option>
            <a-select-option value="sse">SSE（远程服务）</a-select-option>
          </a-select>
        </a-form-item>

        <!-- stdio fields -->
        <template v-if="form.transport === 'stdio'">
          <a-form-item label="命令" required>
            <a-input v-model:value="form.command" placeholder="如：python" />
          </a-form-item>
          <a-form-item label="参数">
            <a-input v-model:value="argsStr" placeholder="如：-m, mcp_server_filesystem, /path" />
          </a-form-item>
        </template>

        <!-- sse fields -->
        <template v-if="form.transport === 'sse'">
          <a-form-item label="URL" required>
            <a-input v-model:value="form.url" placeholder="如：http://localhost:3001/sse" />
          </a-form-item>
        </template>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, computed } from 'vue'
import { message } from 'ant-design-vue'
import { PlusOutlined, DisconnectOutlined } from '@ant-design/icons-vue'
import { api } from '@/utils/api'

const loading = ref(false)
const addLoading = ref(false)
const showAddModal = ref(false)
const connections = ref<any[]>([])

const columns = [
  { title: '名称', dataIndex: 'name', key: 'name' },
  { title: '传输类型', dataIndex: 'transport', key: 'transport' },
  { title: '地址 / 命令', key: 'endpoint',
    customRender: ({ record }: any) => record.url || `${record.command} ${(record.args || []).join(' ')}`
  },
  { title: '状态', key: 'status' },
  { title: '发现工具', key: 'tools' },
  { title: '操作', key: 'action' },
]

const form = reactive({
  name: '',
  transport: 'stdio',
  command: '',
  args: [] as string[],
  url: '',
})

const argsStr = computed({
  get: () => form.args.join(', '),
  set: (val: string) => {
    form.args = val.split(',').map(s => s.trim()).filter(Boolean)
  },
})

async function fetchConnections() {
  loading.value = true
  try {
    const res = await api.get('/mcp/connections')
    connections.value = res.data.connections || []
  } catch (e: any) {
    message.error(e.response?.data?.detail || '获取连接失败')
  } finally {
    loading.value = false
  }
}

async function handleAddConnection() {
  if (!form.name) {
    message.warning('请输入连接名称')
    return
  }
  if (form.transport === 'stdio' && !form.command) {
    message.warning('请输入命令')
    return
  }
  if (form.transport === 'sse' && !form.url) {
    message.warning('请输入 URL')
    return
  }

  addLoading.value = true
  try {
    await api.post('/mcp/connections', {
      name: form.name,
      transport: form.transport,
      command: form.command || undefined,
      args: form.args,
      url: form.url || undefined,
    })
    message.success('连接成功')
    showAddModal.value = false
    resetForm()
    fetchConnections()
  } catch (e: any) {
    message.error(e.response?.data?.detail || '连接失败')
  } finally {
    addLoading.value = false
  }
}

async function disconnect(name: string) {
  try {
    await api.delete(`/mcp/connections/${name}`)
    message.success('已断开连接')
    fetchConnections()
  } catch (e: any) {
    message.error(e.response?.data?.detail || '断开失败')
  }
}

function resetForm() {
  form.name = ''
  form.transport = 'stdio'
  form.command = ''
  form.args = []
  form.url = ''
}

onMounted(fetchConnections)
</script>
