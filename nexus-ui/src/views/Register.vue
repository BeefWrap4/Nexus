<template>
  <div class="register-container">
    <a-card title="注册 NEXUS 账号" style="max-width: 400px; margin: 100px auto;">
      <a-form layout="vertical" @finish="handleSubmit">
        <a-form-item label="姓名" required>
          <a-input v-model:value="name" placeholder="您的姓名" size="large" />
        </a-form-item>
        <a-form-item label="邮箱" required>
          <a-input
            v-model:value="email"
            type="email"
            placeholder="you@example.com"
            size="large"
          />
        </a-form-item>
        <a-form-item label="密码" required>
          <a-input-password
            v-model:value="password"
            placeholder="至少 8 位"
            size="large"
          />
        </a-form-item>
        <a-form-item label="公司/团队名称" required>
          <a-input
            v-model:value="tenantName"
            placeholder="Acme Corp"
            size="large"
          />
        </a-form-item>
        <a-form-item>
          <a-button
            type="primary"
            html-type="submit"
            :loading="loading"
            block
            size="large"
          >
            创建账号
          </a-button>
        </a-form-item>
        <a-typography-text type="secondary" style="display: block; text-align: center; margin-top: 12px">
          已有账号？
          <a-typography-link @click="$router.push('/login')">
            立即登录
          </a-typography-link>
        </a-typography-text>
      </a-form>
      <a-alert
        v-if="error"
        type="error"
        :message="error"
        style="margin-top: 16px"
        show-icon
      />
    </a-card>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { useAuthStore } from '@/stores/auth'
import { authApi } from '@/api'

const router = useRouter()
const auth = useAuthStore()

const name = ref('')
const email = ref('')
const password = ref('')
const tenantName = ref('')
const loading = ref(false)
const error = ref('')

async function handleSubmit() {
  loading.value = true
  error.value = ''
  try {
    const res = await authApi.signup({
      email: email.value,
      password: password.value,
      tenant_name: tenantName.value,
      name: name.value,
    })
    const data = res.data
    // Persist token + user, mirror Login.vue's storage layout
    auth.setToken(data.access_token)
    if (data.refresh_token) {
      localStorage.setItem('nexus_refresh_token', data.refresh_token)
    }
    if (data.user) {
      auth.setUser(data.user)
    }
    message.success('注册成功！欢迎使用 NEXUS')
    router.push('/dashboard')
  } catch (e: any) {
    if (e?.response?.status === 409) {
      error.value = '该邮箱已被注册'
    } else {
      error.value =
        e?.response?.data?.detail || e?.response?.data?.error?.message || '注册失败，请重试'
    }
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.register-container {
  height: 100vh;
  display: flex;
  justify-content: center;
  align-items: center;
  background: #f0f2f5;
}
</style>
