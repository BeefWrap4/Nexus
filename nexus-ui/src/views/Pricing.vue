<template>
  <div class="pricing-container">
    <a-page-header title="选择 NEXUS 计划" sub-title="随时升级或降级" />
    <a-row :gutter="24" justify="center">
      <a-col :span="6" v-for="plan in plans" :key="plan.id">
        <a-card :title="plan.name" :class="['plan-card', { 'featured': plan.featured }]">
          <div class="price">
            <span class="amount">${{ plan.price }}</span>
            <span class="period">/月</span>
          </div>
          <ul class="features">
            <li v-for="feat in plan.features" :key="feat">
              <check-outlined /> {{ feat }}
            </li>
          </ul>
          <a-button
            type="primary"
            size="large"
            block
            :loading="loading === plan.id"
            @click="subscribe(plan.id)"
          >
            {{ plan.id === 'free' ? '当前计划' : `升级到 ${plan.name}` }}
          </a-button>
        </a-card>
      </a-col>
    </a-row>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { message } from 'ant-design-vue'
import { CheckOutlined } from '@ant-design/icons-vue'
import { billingApi } from '@/api'

const loading = ref<string | null>(null)

const plans = [
  {
    id: 'free',
    name: 'Free',
    price: 0,
    features: [
      '10,000 tokens/月',
      '1,000 API calls/月',
      '1 个用户',
      '社区支持',
    ],
  },
  {
    id: 'pro',
    name: 'Pro',
    price: 49,
    featured: true,
    features: [
      '1,000,000 tokens/月',
      '100,000 API calls/月',
      '5 个用户',
      '邮件支持',
      'HITL 审批',
    ],
  },
  {
    id: 'enterprise',
    name: 'Enterprise',
    price: 499,
    features: [
      '100,000,000 tokens/月',
      '10,000,000 API calls/月',
      '无限用户',
      '7x24 支持',
      'SSO / SAML',
      '审计日志',
    ],
  },
]

async function subscribe(planId: string) {
  if (planId === 'free') return
  loading.value = planId
  try {
    const resp = await billingApi.subscribe(planId as 'pro' | 'enterprise')
    // Redirect to Stripe Checkout
    window.location.href = resp.data.checkout_url
  } catch (e: any) {
    message.error(e?.response?.data?.detail || '订阅失败')
  } finally {
    loading.value = null
  }
}
</script>

<style scoped>
.pricing-container { padding: 48px 24px; max-width: 1200px; margin: 0 auto; }
.plan-card { margin-bottom: 24px; }
.plan-card.featured { border-color: #1890ff; box-shadow: 0 4px 12px rgba(24,144,255,0.15); }
.price { text-align: center; margin: 24px 0; }
.price .amount { font-size: 36px; font-weight: bold; }
.price .period { color: #999; margin-left: 4px; }
.features { list-style: none; padding: 0; margin: 24px 0; min-height: 180px; }
.features li { padding: 8px 0; }
</style>
