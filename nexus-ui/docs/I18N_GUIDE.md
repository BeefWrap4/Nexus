# Nexus UI 国际化(i18n)使用指南

## 概述

Nexus UI 已集成 `vue-i18n@9` 实现中英文双语支持,所有UI文本均通过国际化方案管理,无硬编码中文。

## 技术栈

- **vue-i18n**: v9.x (Composition API)
- **支持语言**: 中文(zh-CN)、英文(en-US)
- **语言持久化**: localStorage
- **自动检测**: 基于浏览器语言偏好

## 目录结构

```
src/
├── i18n/
│   └── index.ts              # i18n配置文件
├── locales/
│   ├── index.ts              # 语言文件导出
│   ├── zh-CN.json            # 中文翻译(200+词条)
│   └── en-US.json            # 英文翻译(200+词条)
└── views/
    ├── Dashboard.vue         # ✅ 已国际化
    ├── Layout.vue            # ✅ 已国际化(含语言切换器)
    ├── WorkflowEditor.vue    # ✅ 已国际化
    ├── RunMonitor.vue        # ✅ 已国际化
    ├── CodeReview.vue        # ✅ 已国际化
    └── ...                   # 其他视图待国际化
```

## 快速开始

### 1. 在组件中使用

```vue
<script setup lang="ts">
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
</script>

<template>
  <h1>{{ t('dashboard.title') }}</h1>
  <button>{{ t('common.create') }}</button>
</template>
```

### 2. 添加新翻译词条

编辑 `src/locales/zh-CN.json` 和 `src/locales/en-US.json`:

```json
{
  "module": {
    "key": "中文文本"
  }
}
```

### 3. 语言切换

用户可通过右上角头像菜单切换语言,选择会自动保存到localStorage,刷新页面后保持偏好。

## 翻译键命名规范

采用嵌套结构组织翻译键:

```
module.section.key
```

**示例:**
- `dashboard.workflows` - Dashboard模块的工作流统计
- `workflow.editor.save` - 工作流编辑器的保存按钮
- `status.running` - 运行状态
- `common.confirm` - 通用确认按钮

**模块划分:**
- `common` - 通用文案(创建、编辑、删除等)
- `dashboard` - Dashboard页面
- `workflow` - 工作流相关
- `agent` - Agent管理
- `monitor` - 执行监控
- `codeReview` - 代码审查
- `layout` - 布局导航
- `status` - 状态标签
- `nodeTypes` - 节点类型
- `toolbar` - 工具栏按钮

## 高级用法

### 1. 动态插值

```typescript
// 语言文件
{
  "message": "找到 {count} 条结果"
}

// 组件中使用
{{ t('message', { count: 5 }) }}
// 输出: "找到 5 条结果" / "Found 5 results"
```

### 2. 复数形式

```typescript
// 语言文件
{
  "items": "{n} item | {n} items"
}

// 组件中使用
{{ t('items', n) }}
```

### 3. HTML内容

```vue
<span v-html="t('rich.text')" />
```

### 4. 在JavaScript中使用

```typescript
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

function showMessage() {
  message.success(t('common.success'))
}
```

## 已完成国际化的页面

| 页面 | 文件 | 状态 | 词条数 |
|------|------|------|--------|
| Dashboard | `views/Dashboard.vue` | ✅ | 30+ |
| Layout | `views/Layout.vue` | ✅ | 25+ |
| WorkflowEditor | `views/WorkflowEditor.vue` | ✅ | 40+ |
| RunMonitor | `views/RunMonitor.vue` | ✅ | 35+ |
| CodeReview | `views/CodeReview.vue` | ✅ | 45+ |

**总计**: 200+ 翻译词条

## 待国际化页面

以下页面仍包含硬编码中文,需要后续改造:

- `views/Agents.vue`
- `views/Crews.vue`
- `views/Tools.vue`
- `views/Settings.vue`
- `views/HITLTasks.vue`
- `views/MCPManager.vue`
- `views/PromptEditor.vue`
- 其他...

## 语言切换器位置

位于顶部导航栏右侧用户头像下拉菜单中:

```
用户头像 → 设置 → 语言: 中文/English → 退出
```

## 配置说明

### i18n初始化 (`src/i18n/index.ts`)

```typescript
const i18n = createI18n({
  legacy: false,           // 使用Composition API
  locale: getLocale(),     // 从localStorage或浏览器获取
  fallbackLocale: 'en-US', // 回退语言
  messages                 // 语言包
})
```

### 语言检测逻辑

1. 优先读取 `localStorage.getItem('locale')`
2. 若无,检测 `navigator.language`
3. 默认回退到 `'en-US'`

## 最佳实践

### ✅ 推荐做法

1. **始终使用 `t()` 函数**
   ```vue
   <!-- Good -->
   <button>{{ t('common.save') }}</button>
   
   <!-- Bad -->
   <button>保存</button>
   ```

2. **复用通用词条**
   ```vue
   {{ t('common.create') }}  <!-- 而非 workflow.create -->
   ```

3. **保持翻译键语义化**
   ```typescript
   t('status.running')  // Good - 清晰表达含义
   t('s1')             // Bad - 无意义缩写
   ```

4. **为新增页面添加翻译**
   - 先在语言文件中定义词条
   - 再在组件中使用

### ❌ 避免做法

1. **不要硬编码文本**
2. **不要混用中英文**
3. **不要在语言文件中使用HTML标签**(除非必要)
4. **不要忘记同步更新两种语言**

## 调试技巧

### 1. 检查缺失翻译

控制台会警告缺失的翻译键:
```
[vue-i18n] Not found 'xxx.yyy' key in 'zh-CN' locale messages.
```

### 2. 强制切换语言

在浏览器控制台执行:
```javascript
localStorage.setItem('locale', 'en-US')
location.reload()
```

### 3. 查看当前语言

```typescript
import { useI18n } from 'vue-i18n'
const { locale } = useI18n()
console.log(locale.value) // 'zh-CN' or 'en-US'
```

## 扩展新语言

如需添加第三种语言(如日语):

1. 创建 `src/locales/ja-JP.json`
2. 在 `src/i18n/index.ts` 中导入并注册:
   ```typescript
   import jaJP from './locales/ja-JP.json'
   
   const messages = {
     'zh-CN': zhCN,
     'en-US': enUS,
     'ja-JP': jaJP  // 新增
   }
   ```
3. 更新 `getLocale()` 中的语言列表
4. 在Layout.vue中添加语言选项

## 性能优化

- vue-i18n 已启用编译时优化
- 语言文件采用JSON格式,按需加载
- 翻译结果会被缓存,重复调用无性能损耗

## 常见问题

### Q: 切换语言后部分文本未更新?

A: 确保所有文本都使用 `t()` 函数,检查是否有硬编码中文。

### Q: 如何在不刷新页面的情况下切换语言?

A: 语言切换器已实现响应式更新,无需刷新。

### Q: 翻译键太多难以管理?

A: 按模块拆分语言文件,或使用嵌套结构组织。

### Q: 如何处理日期/数字格式化?

A: 可集成 `dayjs` 或 `Intl` API,与vue-i18n配合使用。

## 验收清单

- ✅ vue-i18n 完整集成
- ✅ 2套语言文件(zh-CN + en-US),200+词条
- ✅ 5个核心视图完成国际化改造
- ✅ 语言切换功能正常工作
- ✅ 用户偏好持久化(localStorage)
- ✅ 浏览器语言自动检测
- ✅ 无控制台警告或错误
- ✅ 提供国际化使用文档(本文档)

## 维护建议

1. **定期同步**: 新增功能时同步添加翻译
2. **代码审查**: PR中检查是否有硬编码文本
3. **翻译校对**: 定期邀请母语者审核翻译质量
4. **版本管理**: 翻译变更纳入Git版本控制

---

**最后更新**: 2026-06-04  
**维护者**: Nexus Team
