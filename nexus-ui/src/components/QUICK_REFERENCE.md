# Nexus 通用组件快速参考

## 组件导入

```typescript
// 方式1: 统一导入（推荐）
import { StatusBadge, DataTable, FormBuilder } from '@/components'
import { WorkflowNode } from '@/components/workflow'

// 方式2: 单独导入
import StatusBadge from '@/components/common/StatusBadge.vue'
import DataTable from '@/components/common/DataTable.vue'
import FormBuilder from '@/components/common/FormBuilder.vue'
import WorkflowNode from '@/components/workflow/WorkflowNode.vue'
```

## 快速示例

### 1. StatusBadge - 状态标签

```vue
<template>
  <StatusBadge status="completed" />
  <StatusBadge status="running" />
  <StatusBadge status="failed" />
</template>
```

**预设状态**: completed, succeeded, running, failed, pending, paused, cancelled, waiting, skipped, hierarchical, sequential, parallel

---

### 2. DataTable - 数据表格

```vue
<template>
  <DataTable
    :columns="columns"
    :data-source="data"
    :loading="loading"
    @refresh="fetchData"
  >
    <template #bodyCell="{ column, record }">
      <template v-if="column.key === 'status'">
        <StatusBadge :status="record.status" />
      </template>
    </template>
  </DataTable>
</template>

<script setup>
const columns = [
  { title: 'ID', dataIndex: 'id', key: 'id' },
  { title: '名称', dataIndex: 'name', key: 'name' },
  { title: '状态', key: 'status' },
]
</script>
```

**常用Props**: searchable, refreshable, showToolbar, pagination, size

---

### 3. FormBuilder - 动态表单

```vue
<template>
  <FormBuilder
    :schema="formSchema"
    @submit="handleSubmit"
  />
</template>

<script setup>
const formSchema = {
  fields: [
    { name: 'username', label: '用户名', type: 'input', required: true },
    { 
      name: 'role', 
      label: '角色', 
      type: 'select',
      options: [
        { label: '管理员', value: 'admin' },
        { label: '用户', value: 'user' },
      ]
    },
  ]
}
</script>
```

**字段类型**: input, textarea, select, radio, checkbox, number, slider, date, switch, custom

---

### 4. WorkflowNode - 工作流节点

```vue
<template>
  <VueFlow v-model="elements" :node-types="nodeTypes">
    <template #node-agent="{ label, selected }">
      <WorkflowNode
        :label="label"
        node-type="agent"
        :selected="selected"
      />
    </template>
  </VueFlow>
</template>
```

**节点类型**: start, agent, tool, hitl, condition, parallel, delay, end

---

## 常见场景

### 替换a-tag状态显示

```vue
<!-- 之前 -->
<a-tag v-if="status === 'completed'" color="green">已完成</a-tag>
<a-tag v-else-if="status === 'failed'" color="red">失败</a-tag>

<!-- 之后 -->
<StatusBadge :status="status" />
```

### 替换a-table列表

```vue
<!-- 之前 -->
<a-table :columns="cols" :dataSource="data" />

<!-- 之后 -->
<DataTable :columns="cols" :data-source="data" />
```

### 快速创建表单

```vue
<!-- 之前：手动写每个表单项 -->
<a-form>
  <a-form-item label="名称"><a-input v-model:value="form.name" /></a-form-item>
  <a-form-item label="角色">
    <a-select v-model:value="form.role">...</a-select>
  </a-form-item>
</a-form>

<!-- 之后：使用schema配置 -->
<FormBuilder :schema="schema" />
```

---

## 详细文档

查看完整文档: `src/components/README.md`
