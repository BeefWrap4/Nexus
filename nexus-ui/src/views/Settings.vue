<template>
  <div>
    <a-page-header title="系统设置" />
    <a-tabs v-model:activeKey="activeTab">
      <a-tab-pane key="general" tab="通用">
        <a-form :model="generalSettings" layout="vertical">
          <a-form-item label="默认超时时间（秒）">
            <a-input-number v-model:value="generalSettings.timeout" :min="10" :max="3600" />
          </a-form-item>
          <a-form-item label="最大迭代次数">
            <a-input-number v-model:value="generalSettings.maxIterations" :min="1" :max="50" />
          </a-form-item>
          <a-form-item label="默认租户ID">
            <a-input v-model:value="generalSettings.defaultTenantId" placeholder="tenant-xxx" />
          </a-form-item>
          <a-form-item>
            <a-button type="primary" :loading="savingGeneral" @click="saveGeneral">保存通用设置</a-button>
          </a-form-item>
        </a-form>
      </a-tab-pane>

      <a-tab-pane key="llm" tab="LLM配置">
        <a-form :model="llmSettings" layout="vertical">
          <a-form-item label="默认模型">
            <a-select v-model:value="llmSettings.defaultModel">
              <a-select-option value="gpt-4o">GPT-4o</a-select-option>
              <a-select-option value="gpt-4o-mini">GPT-4o Mini</a-select-option>
              <a-select-option value="claude-3-sonnet">Claude 3 Sonnet</a-select-option>
              <a-select-option value="glm-4">GLM-4</a-select-option>
            </a-select>
          </a-form-item>
          <a-form-item label="默认温度">
            <a-slider v-model:value="llmSettings.temperature" :min="0" :max="2" :step="0.1" />
          </a-form-item>
          <a-form-item label="最大Token">
            <a-input-number v-model:value="llmSettings.maxTokens" :min="256" :max="8192" :step="256" />
          </a-form-item>
          <a-form-item>
            <a-button type="primary" :loading="savingLLM" @click="saveLLM">保存LLM设置</a-button>
          </a-form-item>
        </a-form>
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
        <a-form :model="securitySettings" layout="vertical">
          <a-form-item label="启用PII过滤">
            <a-switch v-model:checked="securitySettings.piiEnabled" />
          </a-form-item>
          <a-form-item label="启用审计日志">
            <a-switch v-model:checked="securitySettings.auditEnabled" />
          </a-form-item>
          <a-form-item label="会话超时（分钟）">
            <a-input-number v-model:value="securitySettings.sessionTimeout" :min="5" :max="1440" />
          </a-form-item>
          <a-form-item>
            <a-button type="primary" :loading="savingSecurity" @click="saveSecurity">保存安全设置</a-button>
          </a-form-item>
        </a-form>
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
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import api from '@/api'

const activeTab = ref('general')
const savingGeneral = ref(false)
const savingLLM = ref(false)
const savingSecurity = ref(false)

const generalSettings = reactive({ timeout: 120, maxIterations: 10, defaultTenantId: '' })
const llmSettings = reactive({ defaultModel: 'gpt-4o', temperature: 0.7, maxTokens: 4096 })
const securitySettings = reactive({ piiEnabled: true, auditEnabled: true, sessionTimeout: 60 })

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
    const { data } = await api.get('/settings')
    if (data.general) Object.assign(generalSettings, data.general)
    if (data.llm) Object.assign(llmSettings, data.llm)
    if (data.security) Object.assign(securitySettings, data.security)
  } catch {
    // use defaults
  }
  try {
    const { data } = await api.get('/api-keys')
    apiKeys.value = data
  } catch {
    // use defaults
  }
}

async function saveGeneral() {
  savingGeneral.value = true
  try {
    await api.post('/settings/general', generalSettings)
    message.success('通用设置已保存')
  } catch {
    message.error('保存失败')
  } finally {
    savingGeneral.value = false
  }
}

async function saveLLM() {
  savingLLM.value = true
  try {
    await api.post('/settings/llm', llmSettings)
    message.success('LLM设置已保存')
  } catch {
    message.error('保存失败')
  } finally {
    savingLLM.value = false
  }
}

async function saveSecurity() {
  savingSecurity.value = true
  try {
    await api.post('/settings/security', securitySettings)
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
    const { data } = await api.post('/api-keys', { name: newKeyName.value })
    generatedKey.value = data.key
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
