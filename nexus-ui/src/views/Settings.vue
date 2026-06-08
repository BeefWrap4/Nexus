<template>
  <ErrorBoundary>
    <div>
      <a-page-header title="系统设置" />
      <a-tabs v-model:activeKey="activeTab">
        <a-tab-pane key="general" tab="通用">
          <FormBuilder
            :schema="generalSchema"
            :initial-values="generalSettings"
            submit-text="保存通用设置"
            @submit="saveGeneral"
          />
        </a-tab-pane>

        <a-tab-pane key="llm" tab="LLM配置">
          <FormBuilder
            :schema="llmSchema"
            :initial-values="llmSettings"
            submit-text="保存LLM设置"
            @submit="saveLLM"
          />
        </a-tab-pane>

        <a-tab-pane key="api" tab="API密钥">
          <a-space style="margin-bottom: 16px">
            <a-button type="primary" @click="openCreateKey">生成新密钥</a-button>
          </a-space>
          <a-list :dataSource="apiKeys" bordered>
            <template #renderItem="{ item }">
              <a-list-item>
                <a-list-item-meta
                  :title="item.name"
                  :description="`前缀: ${item.prefix} | 创建于: ${formatTime(item.created_at)}`"
                />
                <template #actions>
                  <a-popconfirm title="确定删除此密钥？" @confirm="deleteKey(item.id)">
                    <a-button type="link" danger>删除</a-button>
                  </a-popconfirm>
                </template>
              </a-list-item>
            </template>
          </a-list>
        </a-tab-pane>

        <a-tab-pane key="security" tab="安全">
          <FormBuilder
            :schema="securitySchema"
            :initial-values="securitySettings"
            submit-text="保存安全设置"
            @submit="saveSecurity"
          />
        </a-tab-pane>

        <a-tab-pane key="billing" tab="账单">
          <a-space direction="vertical" style="width: 100%">
            <a-typography-paragraph>
              管理您的订阅计划、支付方式和发票。
            </a-typography-paragraph>
            <a-typography-link @click="$router.push('/billing')">
              管理账单
            </a-typography-link>
          </a-space>
        </a-tab-pane>
      </a-tabs>

      <a-modal v-model:open="keyModalOpen" title="生成API密钥" @ok="createKey">
        <a-form layout="vertical">
          <a-form-item label="密钥名称">
            <a-input v-model:value="newKeyName" placeholder="如: Production Key" />
          </a-form-item>
        </a-form>
        <a-divider />
        <div v-if="generatedKey">
          <a-alert type="warning" message="请立即复制此密钥，关闭后将无法再次查看" show-icon />
          <a-input-group compact style="margin-top: 12px">
            <a-input v-model:value="generatedKey" readonly style="width: calc(100% - 80px)" />
            <a-button @click="copyKey">复制</a-button>
          </a-input-group>
        </div>
      </a-modal>
    </div>
  </ErrorBoundary>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import api from '@/api'
import FormBuilder from '@/components/common/FormBuilder.vue'
import ErrorBoundary from '@/components/common/ErrorBoundary.vue'

const activeTab = ref('general')
const savingGeneral = ref(false)
const savingLLM = ref(false)
const savingSecurity = ref(false)

const generalSettings = reactive({ timeout: 120, maxIterations: 10, defaultTenantId: '' })
const llmSettings = reactive({ defaultModel: 'gpt-4o', temperature: 0.7, maxTokens: 4096 })
const securitySettings = reactive({ piiEnabled: true, auditEnabled: true, sessionTimeout: 60 })

const generalSchema = {
  fields: [
    { name: 'timeout', label: '默认超时时间（秒）', type: 'number' as const, min: 10, max: 3600 },
    { name: 'maxIterations', label: '最大迭代次数', type: 'number' as const, min: 1, max: 50 },
    { name: 'defaultTenantId', label: '默认租户ID', type: 'input' as const, placeholder: 'tenant-xxx' },
  ],
}

const llmSchema = {
  fields: [
    {
      name: 'defaultModel', label: '默认模型', type: 'select' as const,
      options: [
        { label: 'GPT-4o', value: 'gpt-4o' },
        { label: 'GPT-4o Mini', value: 'gpt-4o-mini' },
        { label: 'Claude 3 Sonnet', value: 'claude-3-sonnet' },
        { label: 'GLM-4', value: 'glm-4' },
      ],
    },
    { name: 'temperature', label: '默认温度', type: 'slider' as const, min: 0, max: 2, step: 0.1 },
    { name: 'maxTokens', label: '最大Token', type: 'number' as const, min: 256, max: 8192, step: 256 },
  ],
}

const securitySchema = {
  fields: [
    {
      name: 'piiEnabled',
      label: '启用PII过滤',
      type: 'switch' as const,
      help: 'PII 脱敏总开关。读取 PII_ENABLED 环境变量, 修改本开关后需要重启 API 进程才能生效。',
    },
    {
      name: 'auditEnabled',
      label: '启用审计日志',
      type: 'switch' as const,
      help: 'audit_middleware 启停。写入 SystemSetting 表, 30 秒内对所有 mutating API 生效 (per-tenant)。如未设置, 退回 AUDIT_ENABLED 环境变量。',
    },
    { name: 'sessionTimeout', label: '会话超时（分钟）', type: 'number' as const, min: 5, max: 1440 },
  ],
}

const apiKeys = ref([
  { id: '1', name: 'Production Key', prefix: 'nx_prod_', created_at: '2026-05-01T00:00:00Z' },
  { id: '2', name: 'Development Key', prefix: 'nx_dev_', created_at: '2026-05-15T00:00:00Z' },
])

const keyModalOpen = ref(false)
const newKeyName = ref('')
const generatedKey = ref('')

function formatTime(iso: string) {
  return new Date(iso).toLocaleString('zh-CN')
}

async function fetchSettings() {
  try {
    // axios 响应拦截器直接 return response (没 unwrap), 所以 await api.get(...)
    // 拿到的是 AxiosResponse { data, status, ... }, 真 body 在 .data 里
    // 后端 /api/v1/settings 返 { general, llm, security } 平铺
    const resp = await api.get('/settings')
    const data = resp.data
    if (resp.data.general) Object.assign(generalSettings, data.general)
    if (data.llm) Object.assign(llmSettings, data.llm)
    if (data.security) Object.assign(securitySettings, data.security)
  } catch {
    // use defaults
  }
  try {
    // 同上: /api/v1/api-keys 返 list, 在 resp.data 里
    const resp = await api.get('/api-keys')
    apiKeys.value = resp.data
  } catch {
    // use defaults
  }
}

async function saveGeneral(values: Record<string, any>) {
  savingGeneral.value = true
  try {
    await api.post('/settings/general', values)
    message.success('通用设置已保存')
  } catch {
    message.error('保存失败')
  } finally {
    savingGeneral.value = false
  }
}

async function saveLLM(values: Record<string, any>) {
  savingLLM.value = true
  try {
    await api.post('/settings/llm', values)
    message.success('LLM设置已保存')
  } catch {
    message.error('保存失败')
  } finally {
    savingLLM.value = false
  }
}

async function saveSecurity(values: Record<string, any>) {
  savingSecurity.value = true
  try {
    await api.post('/settings/security', values)
    message.success('安全设置已保存')
  } catch {
    message.error('保存失败')
  } finally {
    savingSecurity.value = false
  }
}

function openCreateKey() {
  newKeyName.value = ''
  generatedKey.value = ''
  keyModalOpen.value = true
}

async function createKey() {
  if (!newKeyName.value) {
    message.warning('请输入密钥名称')
    return
  }
  try {
    const resp = await api.post('/api-keys', { name: newKeyName.value })
    generatedKey.value = resp.data.key
    await fetchSettings()
  } catch {
    message.error('生成密钥失败')
  }
}

async function deleteKey(id: string) {
  try {
    await api.delete(`/api-keys/${id}`)
    message.success('密钥已删除')
    await fetchSettings()
  } catch {
    message.error('删除失败')
  }
}

function copyKey() {
  navigator.clipboard.writeText(generatedKey.value).then(() => {
    message.success('已复制到剪贴板')
  })
}

onMounted(fetchSettings)
</script>
