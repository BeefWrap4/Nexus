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
                <a-menu-item key="settings" @click="$router.push('/settings')">{{ t('common.settings') }}</a-menu-item>
                <a-menu-divider />
                <a-menu-item key="language">
                  <a-dropdown :trigger="['click']">
                    <span>{{ t('layout.language') }}: {{ currentLocale === 'zh-CN' ? t('layout.chinese') : t('layout.english') }}</span>
                    <template #overlay>
                      <a-menu @click="handleLocaleChange">
                        <a-menu-item key="zh-CN">{{ t('layout.chinese') }}</a-menu-item>
                        <a-menu-item key="en-US">{{ t('layout.english') }}</a-menu-item>
                      </a-menu>
                    </template>
                  </a-dropdown>
                </a-menu-item>
                <a-menu-divider />
                <a-menu-item key="logout" @click="logout">{{ t('common.logout') }}</a-menu-item>
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
import { ref, computed, h } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
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
  GithubOutlined,
  AppstoreOutlined,
  TeamOutlined,
  BellOutlined,
  DownOutlined,
} from '@ant-design/icons-vue'

const route = useRoute()
const router = useRouter()
const { locale, t } = useI18n()
const collapsed = ref(false)
const selectedKeys = computed(() => [route.path.split('/')[1] || 'dashboard'])
const pendingHITLCount = ref(0)
const currentLocale = ref(locale.value)

const pageTitle = computed(() => {
  const titles: Record<string, string> = {
    dashboard: t('layout.dashboard'),
    workflows: t('layout.workflows'),
    agents: t('layout.agents'),
    tools: t('layout.tools'),
    runs: t('monitor.title'),
    hitl: t('layout.approvalTasks'),
    mcp: t('layout.mcpManagement'),
    prompts: t('layout.prompts'),
    traces: t('layout.traces'),
    experiments: t('layout.experiments'),
    evals: t('layout.eval'),
    crews: t('layout.crews'),
    'code-review': t('layout.codeReview'),
    'pr-bot': t('layout.prBot'),
    templates: t('layout.templateMarket'),
    analytics: t('layout.analytics'),
    settings: t('layout.settings'),
  }
  return titles[route.path.split('/')[1]] || 'NEXUS'
})

const menuItems = [
  { key: 'dashboard', icon: () => h(DashboardOutlined), label: t('layout.dashboard') },
  { key: 'workflows', icon: () => h(NodeIndexOutlined), label: t('layout.workflows') },
  { key: 'agents', icon: () => h(RobotOutlined), label: t('layout.agents') },
  { key: 'crews', icon: () => h(TeamOutlined), label: t('layout.crews') },
  { key: 'tools', icon: () => h(ToolOutlined), label: t('layout.tools') },
  { key: 'mcp', icon: () => h(ApiOutlined), label: t('layout.mcpManagement') },
  { key: 'prompts', icon: () => h(FileTextOutlined), label: t('layout.prompts') },
  { key: 'traces', icon: () => h(LineChartOutlined), label: t('layout.traces') },
  { key: 'experiments', icon: () => h(ExperimentOutlined), label: t('layout.experiments') },
  { key: 'evals', icon: () => h(AuditOutlined), label: t('layout.eval') },
  { key: 'code-review', icon: () => h(CodeOutlined), label: t('layout.codeReview') },
  { key: 'pr-bot', icon: () => h(GithubOutlined), label: t('layout.prBot') },
  { key: 'templates', icon: () => h(AppstoreOutlined), label: t('layout.templateMarket') },
  { key: 'hitl', icon: () => h(QuestionCircleOutlined), label: t('layout.approvalTasks') },
  { key: 'analytics', icon: () => h(BarChartOutlined), label: t('layout.analytics') },
  { key: 'settings', icon: () => h(SettingOutlined), label: t('layout.settings') },
]

function handleMenuClick({ key }: { key: string }) {
  router.push(`/${key}`)
}

function handleLocaleChange({ key }: { key: string }) {
  locale.value = key
  localStorage.setItem('locale', key)
  currentLocale.value = key
}

function logout() {
  localStorage.removeItem('nexus_token')
  router.push('/login')
}
</script>