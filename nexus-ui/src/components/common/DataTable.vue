<template>
  <div class="data-table">
    <!-- 搜索和工具栏 -->
    <div v-if="showToolbar" class="table-toolbar">
      <a-space>
        <a-input-search
          v-if="searchable"
          v-model:value="searchText"
          placeholder="搜索..."
          style="width: 250px"
          @search="handleSearch"
        >
          <template #prefix><SearchOutlined /></template>
        </a-input-search>
        
        <slot name="toolbar"></slot>
        
        <a-button v-if="refreshable" @click="$emit('refresh')">
          <ReloadOutlined /> 刷新
        </a-button>
      </a-space>
    </div>

    <!-- 表格主体 -->
    <a-table
      :columns="columns"
      :data-source="filteredData"
      :pagination="paginationConfig"
      :loading="loading"
      :row-key="rowKey"
      :scroll="scroll"
      :size="size"
      :row-selection="rowSelection"
      @change="handleTableChange"
      v-bind="$attrs"
    >
      <!-- 透传所有插槽 -->
      <template v-for="(_, name) in $slots" #[name]="slotData">
        <slot :name="name" v-bind="slotData || {}" />
      </template>
    </a-table>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { SearchOutlined, ReloadOutlined } from '@ant-design/icons-vue'
import type { TableProps } from 'ant-design-vue'

interface Column {
  title: string
  dataIndex?: string
  key: string
  width?: number | string
  sorter?: boolean | Function
  filters?: Array<{ text: string; value: any }>
  scopedSlots?: { customRender: string }
  [key: string]: any
}

interface Props {
  columns: Column[]
  dataSource: any[]
  loading?: boolean
  rowKey?: string
  size?: 'small' | 'middle' | 'large'
  searchable?: boolean
  refreshable?: boolean
  showToolbar?: boolean
  pagination?: boolean | object
  scroll?: { x?: number | string; y?: number | string }
  rowSelection?: TableProps['rowSelection']
}

const props = withDefaults(defineProps<Props>(), {
  loading: false,
  rowKey: 'id',
  size: 'small',
  searchable: true,
  refreshable: true,
  showToolbar: true,
  pagination: () => ({ pageSize: 10 }),
})

const emit = defineEmits<{
  (e: 'search', value: string): void
  (e: 'refresh'): void
  (e: 'change', pagination: any, filters: any, sorter: any): void
}>()

const searchText = ref('')
const filteredData = ref(props.dataSource)

// 分页配置
const paginationConfig = computed(() => {
  if (!props.pagination) return false
  
  const defaultPagination = {
    pageSize: 10,
    showSizeChanger: true,
    showQuickJumper: true,
    showTotal: (total: number) => `共 ${total} 条`,
    pageSizeOptions: ['10', '20', '50', '100'],
  }
  
  return typeof props.pagination === 'boolean' 
    ? defaultPagination 
    : { ...defaultPagination, ...props.pagination }
})

// 搜索过滤
function handleSearch(value: string) {
  if (!value) {
    filteredData.value = props.dataSource
  } else {
    const lowerValue = value.toLowerCase()
    filteredData.value = props.dataSource.filter(item => {
      return Object.values(item).some(val => 
        String(val).toLowerCase().includes(lowerValue)
      )
    })
  }
  emit('search', value)
}

// 表格变化处理
function handleTableChange(pagination: any, filters: any, sorter: any) {
  emit('change', pagination, filters, sorter)
}

// 监听数据源变化
watch(() => props.dataSource, (newData) => {
  filteredData.value = newData
  if (!searchText.value) {
    filteredData.value = newData
  }
}, { deep: true })
</script>

<style scoped>
.data-table {
  width: 100%;
}

.table-toolbar {
  margin-bottom: 16px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
</style>
