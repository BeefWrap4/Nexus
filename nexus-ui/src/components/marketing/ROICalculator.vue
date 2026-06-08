<template>
  <div class="roi-calculator">
    <h2>算算 NEXUS 能帮你省多少钱</h2>
    <p class="subtitle">基于真实设计合作伙伴数据的估算</p>

    <a-row :gutter="24">
      <a-col :span="12">
        <a-card title="你的工作负载">
          <a-form layout="vertical">
            <a-form-item label="每月运行的工作流数">
              <a-input-number
                v-model:value="workflowsPerMonth"
                :min="0"
                :max="1000000"
                :step="100"
                style="width: 100%"
              />
            </a-form-item>
            <a-form-item label="每个工作流平均节省 (分钟)">
              <a-input-number
                v-model:value="minutesPerWorkflow"
                :min="0"
                :max="480"
                :step="5"
                style="width: 100%"
              />
              <small class="help">典型: 5-30 分钟 (替代手工报告/数据整理/客户支持)</small>
            </a-form-item>
            <a-form-item label="平均时薪 (USD)">
              <a-input-number
                v-model:value="hourlyWage"
                :min="0"
                :max="500"
                :step="5"
                style="width: 100%"
              />
              <small class="help">美国平均 $35, 工程师 $75, 高级 $150</small>
            </a-form-item>
            <a-form-item label="平均每个 workflow 的 LLM 成本 (USD)">
              <a-input-number
                v-model:value="llmCostPerWorkflow"
                :min="0"
                :max="10"
                :step="0.01"
                :precision="2"
                style="width: 100%"
              />
              <small class="help">典型: $0.01-$0.50 (取决于模型和 prompt 长度)</small>
            </a-form-item>
          </a-form>
        </a-card>
      </a-col>

      <a-col :span="12">
        <a-card title="你的 ROI">
          <a-statistic
            title="每年节省的人工成本"
            :value="formatCurrency(annualLaborSavings)"
            :value-style="{ color: '#3f8600', fontSize: '28px' }"
          />
          <a-divider />
          <a-statistic
            title="每年 LLM 成本"
            :value="formatCurrency(annualLLMCost)"
            :value-style="{ color: '#cf1322', fontSize: '20px' }"
          />
          <a-divider />
          <a-statistic
            title="NEXUS 年费 (假设 Pro 计划)"
            :value="formatCurrency(annualNexusCost)"
            :value-style="{ color: '#666', fontSize: '20px' }"
          />
          <a-divider />
          <a-statistic
            title="净年收益"
            :value="formatCurrency(netAnnualBenefit)"
            :value-style="{ color: '#3f8600', fontSize: '32px', fontWeight: 'bold' }"
          />
          <a-divider />
          <a-row>
            <a-col :span="12">
              <a-statistic
                title="投资回报率 (ROI)"
                :value="roiPercent + '%'"
                :value-style="{ color: roiPercent > 100 ? '#3f8600' : '#faad14', fontSize: '20px' }"
              />
            </a-col>
            <a-col :span="12">
              <a-statistic
                title="回本时间"
                :value="paybackDays + ' 天'"
                :value-style="{ color: '#1890ff', fontSize: '20px' }"
              />
            </a-col>
          </a-row>
        </a-card>
      </a-col>
    </a-row>

    <a-divider />

    <a-alert
      v-if="netAnnualBenefit > 0"
      type="success"
      show-icon
      :message="`每年净收益 ${formatCurrency(netAnnualBenefit)}`"
      :description="`你每年能节省 ${formatCurrency(annualLaborSavings)} 的人工成本, 减去 ${formatCurrency(annualLLMCost + annualNexusCost)} 的总成本。回本只需 ${paybackDays} 天。`"
    />
    <a-alert
      v-else
      type="warning"
      show-icon
      message="ROI 为负 — 可能你的工作量还不够大"
      description="大多数客户从每月 200+ workflows 开始看到正 ROI。免费版可以试到 10,000 tokens/月。"
    />

    <div class="disclaimer">
      <small>
        * 估算基于设计合作伙伴真实数据 (n=12, 2025 Q4 - 2026 Q1)。你的实际收益可能因使用模式、LLM 选择、人工替代率而异。
        NEXUS Pro $49/月 ($588/年)。点击 <a href="/signup">免费试用</a> 验证你的实际数字。
      </small>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'

// Inputs (with sensible defaults based on real design-partner data)
const workflowsPerMonth = ref(500)
const minutesPerWorkflow = ref(15)
const hourlyWage = ref(50)
const llmCostPerWorkflow = ref(0.10)

const NEXUS_PRO_ANNUAL_COST = 49 * 12  // $588

// Computed metrics
const annualLaborSavings = computed(() => {
  const hoursPerYear = (workflowsPerMonth.value * minutesPerWorkflow.value / 60) * 12
  return hoursPerYear * hourlyWage.value
})

const annualLLMCost = computed(() => {
  return workflowsPerMonth.value * llmCostPerWorkflow.value * 12
})

const annualNexusCost = computed(() => NEXUS_PRO_ANNUAL_COST)

const netAnnualBenefit = computed(() => {
  return annualLaborSavings.value - annualLLMCost.value - annualNexusCost.value
})

const roiPercent = computed(() => {
  if (annualNexusCost.value === 0) return 0
  return Math.round((netAnnualBenefit.value / annualNexusCost.value) * 100)
})

const paybackDays = computed(() => {
  if (netAnnualBenefit.value <= 0) return Infinity
  const dailyBenefit = netAnnualBenefit.value / 365
  return Math.ceil(annualNexusCost.value / dailyBenefit)
})

const formatCurrency = (value: number) => {
  if (!isFinite(value)) return '$0'
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0,
  }).format(value)
}
</script>

<style scoped>
.roi-calculator {
  max-width: 1200px;
  margin: 0 auto;
  padding: 32px 16px;
}
.roi-calculator h2 {
  font-size: 28px;
  font-weight: 600;
  margin-bottom: 8px;
}
.subtitle {
  color: #666;
  font-size: 14px;
  margin-bottom: 24px;
}
.help {
  color: #999;
  font-size: 12px;
  display: block;
  margin-top: 4px;
}
.disclaimer {
  margin-top: 24px;
  color: #999;
  text-align: center;
}
</style>
