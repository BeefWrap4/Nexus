<template>
  <div>
    <a-space style="margin-bottom: 16px">
      <a-button type="primary" @click="createWorkflow">
        <PlusOutlined /> 创建工作流
      </a-button>
    </a-space>
    <a-table :columns="columns" :dataSource="workflows" rowKey="id">
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'action'">
          <a-space>
            <a-button size="small" @click="editWorkflow(record.id)">编辑</a-button>
            <a-button size="small" type="primary" @click="triggerRun(record.id)">执行</a-button>
            <a-button size="small" danger @click="deleteWorkflow(record.id)">删除</a-button>
          </a-space>
        </template>
        <template v-if="column.key === 'status'">
          <a-tag :color="record.status === 'active' ? 'green' : record.status === 'draft' ? 'orange' : 'default'">
            {{ record.status }}
          </a-tag>
        </template>
      </template>
    </a-table>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { PlusOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'

const router = useRouter()
const columns = [
  { title: '名称', dataIndex: 'name', key: 'name' },
  { title: '描述', dataIndex: 'description', key: 'description' },
  { title: '状态', dataIndex: 'status', key: 'status' },
  { title: '版本', dataIndex: 'current_version', key: 'version' },
  { title: '执行次数', dataIndex: 'run_count', key: 'runs' },
  { title: '创建时间', dataIndex: 'created_at', key: 'created_at' },
  { title: '操作', key: 'action' },
]

const workflows = ref([
  { id: '1', name: '合同审查', description: '自动审查合同条款', status: 'active', current_version: 3, run_count: 45, created_at: '2026-05-01' },
  { id: '2', name: '数据报表', description: '生成销售报表', status: 'draft', current_version: 1, run_count: 0, created_at: '2026-06-01' },
])

function createWorkflow() {
  message.info('创建工作流')
}

function editWorkflow(id: string) {
  router.push(`/workflows/${id}/edit`)
}

function triggerRun(id: string) {
  message.success(`触发工作流 ${id} 执行`)
}

function deleteWorkflow(id: string) {
  message.warning(`删除工作流 ${id}`)
}
</script>