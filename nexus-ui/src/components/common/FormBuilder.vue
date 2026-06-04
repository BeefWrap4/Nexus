<template>
  <a-form
    :model="formData"
    :layout="layout"
    :label-col="labelCol"
    :wrapper-col="wrapperCol"
    @finish="handleSubmit"
  >
    <template v-for="field in schema.fields" :key="field.name">
      <!-- 条件渲染：根据visibleIf判断是否显示 -->
      <a-form-item
        v-if="!field.visibleIf || shouldShowField(field)"
        :label="field.label"
        :name="field.name"
        :rules="getRules(field)"
        :help="field.help"
      >
        <!-- Input类型 -->
        <a-input
          v-if="field.type === 'input'"
          v-model:value="formData[field.name]"
          :placeholder="field.placeholder"
          :disabled="field.disabled"
          :maxlength="field.maxlength"
        />

        <!-- Textarea类型 -->
        <a-textarea
          v-else-if="field.type === 'textarea'"
          v-model:value="formData[field.name]"
          :placeholder="field.placeholder"
          :rows="field.rows || 4"
          :disabled="field.disabled"
          :maxlength="field.maxlength"
        />

        <!-- Select类型 -->
        <a-select
          v-else-if="field.type === 'select'"
          v-model:value="formData[field.name]"
          :placeholder="field.placeholder"
          :disabled="field.disabled"
          :mode="field.mode"
          allow-clear
        >
          <a-select-option
            v-for="option in field.options"
            :key="option.value"
            :value="option.value"
          >
            {{ option.label }}
          </a-select-option>
        </a-select>

        <!-- Radio Group类型 -->
        <a-radio-group
          v-else-if="field.type === 'radio'"
          v-model:value="formData[field.name]"
          :disabled="field.disabled"
        >
          <a-radio-button
            v-for="option in field.options"
            :key="option.value"
            :value="option.value"
          >
            {{ option.label }}
          </a-radio-button>
        </a-radio-group>

        <!-- Checkbox Group类型 -->
        <a-checkbox-group
          v-else-if="field.type === 'checkbox'"
          v-model:value="formData[field.name]"
          :disabled="field.disabled"
        >
          <a-checkbox
            v-for="option in field.options"
            :key="option.value"
            :value="option.value"
          >
            {{ option.label }}
          </a-checkbox>
        </a-checkbox-group>

        <!-- Number类型 -->
        <a-input-number
          v-else-if="field.type === 'number'"
          v-model:value="formData[field.name]"
          :placeholder="field.placeholder"
          :disabled="field.disabled"
          :min="field.min"
          :max="field.max"
          :step="field.step"
          style="width: 100%"
        />

        <!-- Slider类型 -->
        <a-slider
          v-else-if="field.type === 'slider'"
          v-model:value="formData[field.name]"
          :min="field.min || 0"
          :max="field.max || 100"
          :step="field.step || 1"
          :disabled="field.disabled"
        />

        <!-- Date类型 -->
        <a-date-picker
          v-else-if="field.type === 'date'"
          v-model:value="formData[field.name]"
          :placeholder="field.placeholder"
          :disabled="field.disabled"
          style="width: 100%"
        />

        <!-- Switch类型 -->
        <a-switch
          v-else-if="field.type === 'switch'"
          v-model:checked="formData[field.name]"
          :disabled="field.disabled"
        />

        <!-- 自定义插槽 -->
        <slot
          v-else-if="field.type === 'custom'"
          :name="`field-${field.name}`"
          :field="field"
          :value="formData[field.name]"
          :update="(val: any) => formData[field.name] = val"
        />
      </a-form-item>
    </template>

    <!-- 表单操作按钮 -->
    <a-form-item v-if="showActions" :wrapper-col="{ span: 24 }">
      <a-space>
        <a-button type="primary" html-type="submit" :loading="submitting">
          {{ submitText }}
        </a-button>
        <a-button v-if="showReset" @click="handleReset">重置</a-button>
        <slot name="actions"></slot>
      </a-space>
    </a-form-item>
  </a-form>
</template>

<script setup lang="ts">
import { ref, reactive, watch } from 'vue'
import type { Rule } from 'ant-design-vue/es/form'

interface FieldOption {
  label: string
  value: any
}

interface FormField {
  name: string
  label: string
  type: 'input' | 'textarea' | 'select' | 'radio' | 'checkbox' | 'number' | 'slider' | 'date' | 'switch' | 'custom'
  placeholder?: string
  required?: boolean
  disabled?: boolean
  rules?: Rule[]
  options?: FieldOption[]
  min?: number
  max?: number
  step?: number
  rows?: number
  maxlength?: number
  mode?: 'multiple' | 'tags'
  help?: string
  visibleIf?: Record<string, any>
  defaultValue?: any
}

interface FormSchema {
  fields: FormField[]
}

interface Props {
  schema: FormSchema
  initialValues?: Record<string, any>
  layout?: 'horizontal' | 'vertical' | 'inline'
  labelCol?: any
  wrapperCol?: any
  showActions?: boolean
  showReset?: boolean
  submitText?: string
}

const props = withDefaults(defineProps<Props>(), {
  layout: 'vertical',
  showActions: true,
  showReset: true,
  submitText: '提交',
  initialValues: () => ({}),
})

const emit = defineEmits<{
  (e: 'submit', values: Record<string, any>): void
  (e: 'reset'): void
  (e: 'change', field: string, value: any): void
}>()

// 表单数据
const formData = reactive<Record<string, any>>({})
const submitting = ref(false)

// 初始化表单数据
function initFormData() {
  props.schema.fields.forEach(field => {
    if (props.initialValues[field.name] !== undefined) {
      formData[field.name] = props.initialValues[field.name]
    } else if (field.defaultValue !== undefined) {
      formData[field.name] = field.defaultValue
    } else {
      // 根据类型设置默认值
      if (field.type === 'checkbox') {
        formData[field.name] = []
      } else if (field.type === 'switch') {
        formData[field.name] = false
      } else {
        formData[field.name] = undefined
      }
    }
  })
}

// 获取验证规则
function getRules(field: FormField): Rule[] {
  const rules: Rule[] = [...(field.rules || [])]
  
  if (field.required) {
    rules.unshift({
      required: true,
      message: `${field.label}不能为空`,
      trigger: field.type === 'input' || field.type === 'textarea' ? 'blur' : 'change',
    })
  }
  
  return rules
}

// 判断字段是否应该显示
function shouldShowField(field: FormField): boolean {
  if (!field.visibleIf) return true
  
  return Object.entries(field.visibleIf).every(([fieldName, expectedValue]) => {
    return formData[fieldName] === expectedValue
  })
}

// 提交表单
async function handleSubmit(values: Record<string, any>) {
  submitting.value = true
  try {
    emit('submit', { ...formData, ...values })
  } finally {
    submitting.value = false
  }
}

// 重置表单
function handleReset() {
  initFormData()
  emit('reset')
}

// 监听字段变化
watch(formData, (newVal, oldVal) => {
  Object.keys(newVal).forEach(key => {
    if (newVal[key] !== oldVal?.[key]) {
      emit('change', key, newVal[key])
    }
  })
}, { deep: true })

// 初始化
initFormData()
</script>

<style scoped>
/* 无额外样式，使用Ant Design默认样式 */
</style>
