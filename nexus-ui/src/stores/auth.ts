import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(localStorage.getItem('nexus_token'))
  const user = ref<{ id: string; email: string; name: string; role: string; tenant_id: string } | null>(
    JSON.parse(localStorage.getItem('nexus_user') || 'null'),
  )
  const isAuthenticated = computed(() => !!token.value)

  function setToken(newToken: string) {
    token.value = newToken
    localStorage.setItem('nexus_token', newToken)
  }

  function setUser(newUser: { id: string; email: string; name: string; role: string; tenant_id: string }) {
    user.value = newUser
    localStorage.setItem('nexus_user', JSON.stringify(newUser))
  }

  function logout() {
    token.value = null
    user.value = null
    localStorage.removeItem('nexus_token')
    localStorage.removeItem('nexus_user')
    localStorage.removeItem('nexus_refresh_token')
  }

  return { token, user, isAuthenticated, setToken, setUser, logout }
})
