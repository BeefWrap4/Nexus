<template>
  <div class="login-container">
    <a-card title="NEXUS - 登录" style="width: 400px">
      <a-form :model="form" @finish="handleLogin">
        <a-form-item name="email" :rules="[{ required: true, message: '请输入邮箱' }]">
          <a-input v-model:value="form.email" placeholder="邮箱" size="large" />
        </a-form-item>
        <a-form-item name="password" :rules="[{ required: true, message: '请输入密码' }]">
          <a-input-password v-model:value="form.password" placeholder="密码" size="large" />
        </a-form-item>
        <a-form-item>
          <a-button type="primary" html-type="submit" size="large" block :loading="loading">
            登录
          </a-button>
        </a-form-item>
        <a-typography-text type="secondary" style="display: block; text-align: center; margin-top: 12px">
          还没有账号？
          <a-typography-link @click="$router.push('/register')">
            立即注册
          </a-typography-link>
        </a-typography-text>
        <a-typography-text type="secondary" style="display: block; text-align: center; margin-top: 8px">
          <a-typography-link @click="$router.push('/pricing')">
            查看定价
          </a-typography-link>
        </a-typography-text>
      </a-form>
    </a-card>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { authApi } from '@/api'
import { message } from 'ant-design-vue'

const router = useRouter()
const auth = useAuthStore()
const loading = ref(false)
const form = reactive({ email: '', password: '' })

async function handleLogin() {
  if (!form.email || !form.password) {
    message.error('Please enter email and password')
    return
  }
  loading.value = true
  try {
    const res = await authApi.login({ email: form.email, password: form.password })
    // 修复 (前端 Bug): 后端 OAuth2 风格返回 access_token, 不是 token
    // (res.data 已经是完整后端 payload, 因为没装响应包装拦截器)
    auth.setToken(res.data.access_token)
    if (res.data.refresh_token) {
      localStorage.setItem('nexus_refresh_token', res.data.refresh_token)
    }
    if (res.data.user) {
      auth.setUser(res.data.user)
    }
    message.success('Login successful')
    router.push('/dashboard')
  } catch (err: any) {
    message.error(err.response?.data?.error?.message || 'Login failed')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-container {
  height: 100vh;
  display: flex;
  justify-content: center;
  align-items: center;
  background: #f0f2f5;
}
</style>