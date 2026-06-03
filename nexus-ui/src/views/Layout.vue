<template>
  <a-layout style="min-height: 100vh">
    <a-layout-sider v-model:collapsed="collapsed" collapsible theme="dark" width="220">
      <div class="logo">
        <h3 style="color: white; text-align: center; margin: 16px 0">NEXUS</h3>
      </div>
      <a-menu
        v-model:selectedKeys="selectedKeys"
        theme="dark"
        mode="inline"
        :items="menuItems"
        @click="handleMenuClick"
      />
    </a-layout-sider>
    <a-layout>
      <a-layout-header style="background: #fff; padding: 0 24px; display: flex; justify-content: space-between; align-items: center">
        <h2 style="margin: 0">{{ pageTitle }}</h2>
        <a-space>
          <a-badge :count="pendingHITLCount">
            <a-button shape="circle" @click="$router.push('/hitl')">
              <template #icon><BellOutlined /></template>
            </a-button>
          </a-badge>
          <a-dropdown>
            <a-avatar style="background-color: #1677ff">U</a-avatar>
            <template #overlay>
              <a-menu>
                <a-menu-item key="settings" @click="$router.push('/settings')">设置</a-menu-item>
                <a-menu-item key="logout" @click="logout">退出</a-menu-item>
              </a-menu>
            </template>
          </a-dropdown>
        </a-space>
      </a-layout-header>
      <a-layout-content style="margin: 24px 16px; padding: 24px; background: #fff; border-radius: 8px; overflow-y: auto">
        <router-view />
      </a-layout-content>
    </a-layout>
  </a-layout>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  DashboardOutlined,
  NodeIndexOutlined,
  RobotOutlined,
  ToolOutlined,
  QuestionCircleOutlined,
  BarChartOutlined,
  SettingOutlined,
  ApiOutlined,
  FileTextOutlined,
  LineChartOutlined,
  ExperimentOutlined,
  AuditOutlined,
  CodeOutlined,
} from '@ant-design/icons-vue'

const route = useRoute()
const router = useRouter()
const collapsed = ref(false)
const selectedKeys = computed(() => [route.path.split('/')[1] || 'dashboard'])
const pendingHITLCount = ref(0)

const pageTitle = computed(() => {
  const titles: Record<string, string> = {
    dashboard: 'Dashboard',
    workflows: '工作流',
    agents: 'Agents',
    tools: '工具',
    runs: '执行监控',
    hitl: '审批任务',
    mcp: 'MCP 管理',
    prompts: 'Prompt 管理',
    traces: 'LLM Trace',
    experiments: 'A/B 实验',
    evals: 'Eval 评估',
    'code-review': '代码审查',
    analytics: '分析',
    settings: '设置',
  }
  return titles[route.path.split('/')[1]] || 'NEXUS'
})

const menuItems = [
  { key: 'dashboard', icon: () => h(DashboardOutlined), label: 'Dashboard' },
  { key: 'workflows', icon: () => h(NodeIndexOutlined), label: '工作流' },
  { key: 'agents', icon: () => h(RobotOutlined), label: 'Agents' },
  { key: 'tools', icon: () => h(ToolOutlined), label: '工具' },
  { key: 'mcp', icon: () => h(ApiOutlined), label: 'MCP 管理' },
  { key: 'prompts', icon: () => h(FileTextOutlined), label: 'Prompts' },
  { key: 'traces', icon: () => h(LineChartOutlined), label: 'Traces' },
  { key: 'experiments', icon: () => h(ExperimentOutlined), label: '实验' },
  { key: 'evals', icon: () => h(AuditOutlined), label: 'Eval' },
  { key: 'code-review', icon: () => h(CodeOutlined), label: '代码审查' },
  { key: 'hitl', icon: () => h(QuestionCircleOutlined), label: '审批任务' },
  { key: 'analytics', icon: () => h(BarChartOutlined), label: '分析' },
  { key: 'settings', icon: () => h(SettingOutlined), label: '设置' },
]

function handleMenuClick({ key }: { key: string }) {
  router.push(`/${key}`)
}

function logout() {
  localStorage.removeItem('nexus_token')
  router.push('/login')
}

import { h } from 'vue'
</script>