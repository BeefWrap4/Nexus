import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(localStorage.getItem('nexus_token'))
  const isAuthenticated = computed(() => !!token.value)

  function setToken(newToken: string) {
    token.value = newToken
    localStorage.setItem('nexus_token', newToken)
  }

  function logout() {
    token.value = null
    localStorage.removeItem('nexus_token')
  }

  return { token, isAuthenticated, setToken, logout }
})
