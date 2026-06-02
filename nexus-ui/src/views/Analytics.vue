<template>
  <div>
    <h2>使用分析</h2>
    <a-row :gutter="16" style="margin-top: 16px">
      <a-col :span="12">
        <a-card title="执行趋势">
          <p>最近7天执行次数: 128</p>
          <p>成功率: 94.5%</p>
          <p>平均耗时: 15.3s</p>
        </a-card>
      </a-col>
      <a-col :span="12">
        <a-card title="LLM调用成本">
          <p>今日Token消耗: 2.4M</p>
          <p>今日成本: $12.50</p>
          <p>本月累计: $285.30</p>
        </a-card>
      </a-col>
    </a-row>
    <a-card title="Agent性能" style="margin-top: 16px">
      <a-table :columns="agentColumns" :dataSource="agentStats" :pagination="false" />
    </a-card>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

const agentColumns = [
  { title: 'Agent', dataIndex: 'name' },
  { title: '调用次数', dataIndex: 'calls' },
  { title: '成功率', dataIndex: 'success_rate' },
  { title: '平均耗时', dataIndex: 'avg_time' },
  { title: 'Token消耗', dataIndex: 'tokens' },
]

const agentStats = ref([
  { name: '合同审查员', calls: 45, success_rate: '98%', avg_time: '8.2s', tokens: '1.2M' },
  { name: '数据分析师', calls: 32, success_rate: '95%', avg_time: '12.1s', tokens: '890K' },
])
</script>