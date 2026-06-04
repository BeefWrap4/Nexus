# Nexus UI 通用组件库

本文档介绍Nexus项目中抽取的4个可复用通用组件，用于提升代码复用率和开发效率。

## 目录结构

```
src/components/
├── common/              # 通用业务组件
│   ├── StatusBadge.vue  # 状态标签组件
│   ├── DataTable.vue    # 数据表格组件
│   └── FormBuilder.vue  # 动态表单生成器
└── workflow/            # 工作流相关组件
    └── WorkflowNode.vue # 工作流节点卡片
```

---

## 1. StatusBadge - 状态标签组件

统一展示各种业务状态，支持多种预设状态和自定义配置。

### 使用示例

```vue
<template>
  <!-- 基本用法 -->
  <StatusBadge status="completed" />
  
  <!-- 运行中状态 -->
  <StatusBadge status="running" />
  
  <!-- 失败状态 -->
  <StatusBadge status="failed" />
  
  <!-- 自定义类型 -->
  <StatusBadge status="custom" type="warning" custom-text="自定义状态" />
  
  <!-- 不显示图标 -->
  <StatusBadge status="completed" :show-icon="false" />
</template>

<script setup>
import StatusBadge from '@/components/common/StatusBadge.vue'
</script>
```

### Props

| 参数 | 说明 | 类型 | 默认值 |
|------|------|------|--------|
| status | 状态值 | `string` | - |
| type | 自定义类型（当status无预设映射时使用） | `'success' \| 'warning' \| 'error' \| 'info' \| 'default' \| 'processing'` | `'default'` |
| customText | 自定义文本（当status无预设映射时使用） | `string` | - |
| showIcon | 是否显示图标 | `boolean` | `true` |

### 预设状态映射

- **工作流执行状态**: `completed`, `succeeded`, `running`, `failed`, `pending`, `paused`, `cancelled`
- **节点执行状态**: `waiting`, `skipped`
- **Crew模式**: `hierarchical`, `sequential`, `parallel`

### 最佳实践

✅ **推荐**：直接使用预设状态值，自动匹配颜色和图标
```vue
<StatusBadge :status="workflow.status" />
```

❌ **避免**：手动判断状态并设置颜色
```vue
<!-- 不推荐 -->
<a-tag v-if="status === 'completed'" color="green">已完成</a-tag>
<a-tag v-else-if="status === 'failed'" color="red">失败</a-tag>
```

---

## 2. DataTable - 数据表格组件

封装Ant Design Vue的Table组件，提供搜索、分页、刷新等常用功能。

### 使用示例

```vue
<template>
  <DataTable
    :columns="columns"
    :data-source="tableData"
    :loading="loading"
    :pagination="{ pageSize: 10 }"
    @refresh="fetchData"
    @search="handleSearch"
  >
    <!-- 自定义列渲染 -->
    <template #bodyCell="{ column, record }">
      <template v-if="column.key === 'status'">
        <StatusBadge :status="record.status" />
      </template>
      <template v-if="column.key === 'action'">
        <a-button size="small" @click="handleEdit(record)">编辑</a-button>
      </template>
    </template>
    
    <!-- 工具栏插槽 -->
    <template #toolbar>
      <a-button type="primary" @click="handleCreate">新建</a-button>
    </template>
  </DataTable>
</template>

<script setup>
import { ref } from 'vue'
import DataTable from '@/components/common/DataTable.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'

const columns = [
  { title: 'ID', dataIndex: 'id', key: 'id' },
  { title: '名称', dataIndex: 'name', key: 'name' },
  { title: '状态', dataIndex: 'status', key: 'status' },
  { title: '操作', key: 'action' },
]

const tableData = ref([])
const loading = ref(false)

async function fetchData() {
  loading.value = true
  // 获取数据逻辑
  loading.value = false
}

function handleSearch(value) {
  console.log('搜索:', value)
}
</script>
```

### Props

| 参数 | 说明 | 类型 | 默认值 |
|------|------|------|--------|
| columns | 列配置 | `Column[]` | - |
| dataSource | 数据源 | `any[]` | - |
| loading | 加载状态 | `boolean` | `false` |
| rowKey | 行唯一标识 | `string` | `'id'` |
| size | 表格尺寸 | `'small' \| 'middle' \| 'large'` | `'small'` |
| searchable | 是否显示搜索框 | `boolean` | `true` |
| refreshable | 是否显示刷新按钮 | `boolean` | `true` |
| showToolbar | 是否显示工具栏 | `boolean` | `true` |
| pagination | 分页配置 | `boolean \| object` | `{ pageSize: 10 }` |
| scroll | 滚动配置 | `{ x?: number \| string; y?: number \| string }` | - |
| rowSelection | 行选择配置 | `TableProps['rowSelection']` | - |

### Events

| 事件名 | 说明 | 回调参数 |
|--------|------|----------|
| search | 搜索时触发 | `(value: string)` |
| refresh | 点击刷新按钮时触发 | - |
| change | 表格变化时触发（分页/排序/过滤） | `(pagination, filters, sorter)` |

### Slots

| 插槽名 | 说明 | 作用域参数 |
|--------|------|------------|
| toolbar | 工具栏自定义内容 | - |
| bodyCell | 单元格自定义渲染 | `{ column, record, index }` |
| * | 透传所有a-table原生插槽 | - |

### 最佳实践

✅ **推荐**：关闭不需要的功能以提升性能
```vue
<!-- 如果不需要搜索和刷新 -->
<DataTable 
  :searchable="false" 
  :refreshable="false"
  :show-toolbar="false"
/>
```

✅ **推荐**：使用插槽自定义复杂列渲染
```vue
<template #bodyCell="{ column, record }">
  <template v-if="column.key === 'actions'">
    <a-space>
      <a-button size="small">编辑</a-button>
      <a-button size="small" danger>删除</a-button>
    </a-space>
  </template>
</template>
```

---

## 3. FormBuilder - 动态表单生成器

根据JSON schema自动生成表单，支持多种字段类型和动态验证。

### 使用示例

```vue
<template>
  <FormBuilder
    :schema="formSchema"
    :initial-values="initialData"
    @submit="handleSubmit"
    @reset="handleReset"
    @change="handleFieldChange"
  />
</template>

<script setup>
import { reactive } from 'vue'
import FormBuilder from '@/components/common/FormBuilder.vue'

const formSchema = {
  fields: [
    {
      name: 'username',
      label: '用户名',
      type: 'input',
      required: true,
      placeholder: '请输入用户名',
    },
    {
      name: 'role',
      label: '角色',
      type: 'select',
      required: true,
      options: [
        { label: '管理员', value: 'admin' },
        { label: '用户', value: 'user' },
      ],
    },
    {
      name: 'description',
      label: '描述',
      type: 'textarea',
      rows: 4,
    },
    {
      name: 'priority',
      label: '优先级',
      type: 'radio',
      options: [
        { label: '高', value: 'high' },
        { label: '中', value: 'medium' },
        { label: '低', value: 'low' },
      ],
      defaultValue: 'medium',
    },
    {
      name: 'tags',
      label: '标签',
      type: 'checkbox',
      options: [
        { label: '重要', value: 'important' },
        { label: '紧急', value: 'urgent' },
      ],
    },
    {
      name: 'temperature',
      label: '温度',
      type: 'slider',
      min: 0,
      max: 2,
      step: 0.1,
      defaultValue: 0.7,
    },
    {
      name: 'enabled',
      label: '启用',
      type: 'switch',
      defaultValue: true,
    },
  ],
}

const initialData = reactive({
  username: '',
  role: '',
})

function handleSubmit(values) {
  console.log('表单提交:', values)
}

function handleReset() {
  console.log('表单重置')
}

function handleFieldChange(field, value) {
  console.log(`字段 ${field} 变更为:`, value)
}
</script>
```

### Props

| 参数 | 说明 | 类型 | 默认值 |
|------|------|------|--------|
| schema | 表单schema定义 | `FormSchema` | - |
| initialValues | 初始值 | `Record<string, any>` | `{}` |
| layout | 布局方式 | `'horizontal' \| 'vertical' \| 'inline'` | `'vertical'` |
| labelCol | 标签布局 | `object` | - |
| wrapperCol | 控件布局 | `object` | - |
| showActions | 是否显示操作按钮 | `boolean` | `true` |
| showReset | 是否显示重置按钮 | `boolean` | `true` |
| submitText | 提交按钮文本 | `string` | `'提交'` |

### Events

| 事件名 | 说明 | 回调参数 |
|--------|------|----------|
| submit | 表单提交时触发 | `(values: Record<string, any>)` |
| reset | 表单重置时触发 | - |
| change | 字段值变化时触发 | `(field: string, value: any)` |

### Schema字段类型

支持的字段类型：
- `input` - 单行文本输入
- `textarea` - 多行文本输入
- `select` - 下拉选择（支持多选）
- `radio` - 单选按钮组
- `checkbox` - 复选框组
- `number` - 数字输入
- `slider` - 滑块
- `date` - 日期选择
- `switch` - 开关
- `custom` - 自定义（使用插槽）

### 字段配置

每个字段支持以下配置：

```typescript
interface FormField {
  name: string              // 字段名
  label: string             // 标签文本
  type: string              // 字段类型
  placeholder?: string      // 占位符
  required?: boolean        // 是否必填
  disabled?: boolean        // 是否禁用
  rules?: Rule[]            // 自定义验证规则
  options?: FieldOption[]   // 选项列表（select/radio/checkbox）
  min?: number              // 最小值（number/slider）
  max?: number              // 最大值（number/slider）
  step?: number             // 步长（number/slider）
  rows?: number             // 行数（textarea）
  maxlength?: number        // 最大长度（input/textarea）
  mode?: 'multiple' | 'tags' // 多选模式（select）
  help?: string             // 帮助文本
  visibleIf?: Record<string, any> // 条件显示
  defaultValue?: any        // 默认值
}
```

### 最佳实践

✅ **推荐**：使用visibleIf实现动态字段显示
```javascript
{
  name: 'advancedOptions',
  label: '高级选项',
  type: 'input',
  visibleIf: { showAdvanced: true }  // 仅当showAdvanced为true时显示
}
```

✅ **推荐**：使用自定义插槽处理复杂字段
```vue
<FormBuilder :schema="schema">
  <template #field-customField="{ field, value, update }">
    <CustomComponent :value="value" @update="update" />
  </template>
</FormBuilder>
```

---

## 4. WorkflowNode - 工作流节点卡片

用于Vue Flow工作流编辑器的自定义节点组件，展示节点信息和状态。

### 使用示例

```vue
<template>
  <VueFlow v-model="elements" :node-types="nodeTypes">
    <template #node-agent="{ label, data, selected }">
      <WorkflowNode
        :label="label"
        node-type="agent"
        :selected="selected"
        :status="data?.status"
        badge="A"
        :data="data"
      />
    </template>
    
    <template #node-tool="{ label, selected }">
      <WorkflowNode
        :label="label"
        node-type="tool"
        :selected="selected"
      />
    </template>
  </VueFlow>
</template>

<script setup>
import { VueFlow } from '@vue-flow/core'
import WorkflowNode from '@/components/workflow/WorkflowNode.vue'

const nodeTypes = {
  agent: 'agent',
  tool: 'tool',
  // ... 其他节点类型
}

const elements = ref([
  {
    id: 'node-1',
    type: 'agent',
    label: 'AI助手',
    position: { x: 100, y: 100 },
    data: { status: 'running' },
  },
])
</script>
```

### Props

| 参数 | 说明 | 类型 | 默认值 |
|------|------|------|--------|
| label | 节点标签 | `string` | `''` |
| nodeType | 节点类型 | `string` | `'default'` |
| selected | 是否选中 | `boolean` | `false` |
| status | 节点状态 | `string` | - |
| badge | 徽章文本 | `string` | - |
| showTarget | 是否显示输入连接点 | `boolean` | `true` |
| showSource | 是否显示输出连接点 | `boolean` | `true` |
| sourceHandleId | 输出连接点ID | `string` | - |
| data | 节点数据 | `Record<string, any>` | `{}` |

### 支持的节点类型

| 类型 | 图标 | 边框颜色 |
|------|------|----------|
| start | PlayCircleOutlined | 绿色 |
| agent | RobotOutlined | 紫色 |
| tool | ToolOutlined | 蓝色 |
| hitl | PauseCircleOutlined | 橙色 |
| condition | QuestionCircleOutlined | 粉色 |
| parallel | ForkOutlined | 青色 |
| delay | ClockCircleOutlined | 黄色 |
| end | CheckCircleOutlined | 绿色 |

### 最佳实践

✅ **推荐**：为不同类型的节点使用对应的nodeType
```vue
<WorkflowNode node-type="agent" label="AI助手" />
<WorkflowNode node-type="tool" label="搜索工具" />
```

✅ **推荐**：传递status属性实时显示节点执行状态
```vue
<WorkflowNode 
  :label="node.label" 
  :status="node.status"
  node-type="agent"
/>
```

---

## 迁移指南

### 从原生Ant Design组件迁移

#### 1. 状态标签迁移

**迁移前：**
```vue
<a-tag v-if="status === 'completed'" color="green">已完成</a-tag>
<a-tag v-else-if="status === 'failed'" color="red">失败</a-tag>
<a-tag v-else-if="status === 'running'" color="blue">运行中</a-tag>
```

**迁移后：**
```vue
<StatusBadge :status="status" />
```

#### 2. 表格迁移

**迁移前：**
```vue
<a-table 
  :columns="columns" 
  :dataSource="data" 
  :pagination="pagination"
  :loading="loading"
>
  <template #bodyCell="{ column, record }">
    <!-- 自定义渲染 -->
  </template>
</a-table>
```

**迁移后：**
```vue
<DataTable
  :columns="columns"
  :data-source="data"
  :pagination="pagination"
  :loading="loading"
>
  <template #bodyCell="{ column, record }">
    <!-- 自定义渲染 -->
  </template>
</DataTable>
```

#### 3. 表单迁移

**迁移前：**
```vue
<a-form layout="vertical">
  <a-form-item label="名称" required>
    <a-input v-model:value="form.name" />
  </a-form-item>
  <a-form-item label="角色">
    <a-select v-model:value="form.role">
      <a-select-option value="admin">管理员</a-select-option>
      <a-select-option value="user">用户</a-select-option>
    </a-select>
  </a-form-item>
</a-form>
```

**迁移后：**
```vue
<FormBuilder
  :schema="{
    fields: [
      { name: 'name', label: '名称', type: 'input', required: true },
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
  }"
  @submit="handleSubmit"
/>
```

---

## 常见问题

### Q1: 如何扩展StatusBadge的预设状态？

修改 `StatusBadge.vue` 中的 `statusMap` 对象：

```javascript
const statusMap = {
  // 添加新的状态映射
  myCustomStatus: { color: 'cyan', text: '自定义状态', icon: undefined },
}
```

### Q2: DataTable如何实现服务端分页？

监听 `@change` 事件，在回调中重新获取数据：

```vue
<DataTable
  :data-source="tableData"
  :pagination="pagination"
  @change="handleTableChange"
/>

<script setup>
function handleTableChange(pagination, filters, sorter) {
  // 根据分页参数重新请求数据
  fetchData({
    page: pagination.current,
    pageSize: pagination.pageSize,
    sortField: sorter.field,
    sortOrder: sorter.order,
  })
}
</script>
```

### Q3: FormBuilder如何实现级联选择？

使用 `visibleIf` 或监听 `@change` 事件动态更新schema：

```vue
<FormBuilder
  :schema="dynamicSchema"
  @change="handleFieldChange"
/>

<script setup>
function handleFieldChange(field, value) {
  if (field === 'category') {
    // 根据分类动态更新子类别选项
    dynamicSchema.fields.find(f => f.name === 'subcategory').options = 
      getSubcategories(value)
  }
}
</script>
```

---

## 贡献指南

如需新增通用组件或改进现有组件，请遵循以下原则：

1. **单一职责**：每个组件只负责一个明确的功能
2. **高度复用**：确保组件在至少2个视图中有使用场景
3. **类型安全**：提供完整的TypeScript类型定义
4. **文档完善**：更新本文档，包含使用示例和最佳实践
5. **向后兼容**：避免破坏性变更，保持API稳定

---

## 版本历史

- **v1.0.0** (2026-06-04)
  - 初始版本：StatusBadge, DataTable, FormBuilder, WorkflowNode
  - 重构Dashboard.vue和RunMonitor.vue
