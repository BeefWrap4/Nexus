<template>
  <div class="template-market">
    <a-page-header :title="t('templateMarket.title')" :sub-title="t('templateMarket.subtitle')">
      <template #extra>
        <a-button type="primary" @click="refreshTemplates">
          <template #icon><ReloadOutlined /></template>
          {{ t('common.refresh') }}
        </a-button>
      </template>
    </a-page-header>

    <ErrorBoundary>
      <a-spin :spinning="loading">
        <a-row :gutter="[16, 16]" style="padding: 24px">
          <a-col v-for="tmpl in templates" :key="tmpl.name" :xs="24" :sm="12" :lg="8">
            <a-card :title="tmpl.name" hoverable>
              <template #extra>
                <a-tag :color="tmpl.type === 'crew' ? 'purple' : 'blue'">
                  {{ tmpl.type }}
                </a-tag>
              </template>
              <p>{{ tmpl.description }}</p>
              <p>
                <a-tag>{{ tmpl.version }}</a-tag>
                <a-tag v-if="tmpl.agent" color="green">{{ tmpl.agent.name }}</a-tag>
              </p>
              <template #actions>
                <a-button type="primary" size="small" @click="installTemplate(tmpl.name)">
                  <template #icon><DownloadOutlined /></template>
                  {{ t('templateMarket.install') }}
                </a-button>
                <a-button size="small" @click="showDetail(tmpl)">
                  <template #icon><EyeOutlined /></template>
                  {{ t('templateMarket.details') }}
                </a-button>
              </template>
            </a-card>
          </a-col>
        </a-row>
        <EmptyState v-if="!loading && templates.length === 0" description="No templates available" />
      </a-spin>
    </ErrorBoundary>

    <a-modal v-model:open="detailVisible" title="Template Details" width="700px" :footer="null">
      <pre v-if="selectedTemplate" style="max-height: 400px; overflow: auto; background: #f5f5f5; padding: 16px; border-radius: 8px;">{{ JSON.stringify(selectedTemplate, null, 2) }}</pre>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ReloadOutlined, DownloadOutlined, EyeOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import { useI18n } from 'vue-i18n'
import ErrorBoundary from '@/components/common/ErrorBoundary.vue'
import EmptyState from '@/components/common/EmptyState.vue'

const { t } = useI18n()

interface Template {
  name: string
  version: string
  type: string
  description: string
  agent?: { name: string }
  crew?: { name: string }
}

const templates = ref<Template[]>([])
const loading = ref(false)
const detailVisible = ref(false)
const selectedTemplate = ref<Template | null>(null)

async function refreshTemplates() {
  loading.value = true
  try {
    const data = [
      {
        name: 'code-reviewer-v2',
        version: '2.0.0',
        type: 'agent',
        description: 'Enhanced code review with multi-language support, security scanning, and style checks',
        agent: { name: 'CodeReviewer' }
      },
      {
        name: 'data-analyst',
        version: '1.0.0',
        type: 'agent',
        description: 'Data analysis agent that reads files, runs analysis, and generates reports',
        agent: { name: 'DataAnalyst' }
      },
      {
        name: 'customer-service',
        version: '1.0.0',
        type: 'crew',
        description: 'Multi-agent customer service team with triage, specialist, and supervisor',
        crew: { name: 'CustomerServiceTeam' }
      }
    ]
    templates.value = data
  } catch (e: any) {
    message.error(t('templateMarket.loadFailed'))
  } finally {
    loading.value = false
  }
}

async function installTemplate(name: string) {
  try {
    message.loading({ content: t('templateMarket.installing', { name }), key: 'install' })
    // API call: POST /api/v1/templates/{name}/install
    await new Promise(resolve => setTimeout(resolve, 500))
    message.success({ content: t('templateMarket.installSuccess', { name }), key: 'install' })
  } catch (e: any) {
    message.error({ content: t('templateMarket.installFailed', { name }), key: 'install' })
  }
}

function showDetail(tmpl: Template) {
  selectedTemplate.value = tmpl
  detailVisible.value = true
}

onMounted(() => {
  refreshTemplates()
})
</script>
