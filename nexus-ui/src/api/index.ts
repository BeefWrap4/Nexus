import axios, { AxiosError, type AxiosResponse, type InternalAxiosRequestConfig } from 'axios'
import { message } from 'ant-design-vue'

const api = axios.create({
  baseURL: (import.meta as any).env.VITE_API_BASE_URL || '/api/v1',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// 请求拦截器
api.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const token = localStorage.getItem('nexus_token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    const apiKey = localStorage.getItem('nexus_api_key')
    if (apiKey) {
      config.headers['X-API-Key'] = apiKey
    }
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// 响应拦截器
api.interceptors.response.use(
  (response: AxiosResponse) => response,
  (error: AxiosError) => {
    if (error.response) {
      const status = error.response.status
      const data = error.response.data as any
      const detail = data?.detail || data?.message || error.message

      switch (status) {
        case 400:
          message.error(`请求错误: ${detail}`)
          break
        case 401:
          message.error('登录已过期，请重新登录')
          localStorage.removeItem('nexus_token')
          localStorage.removeItem('nexus_api_key')
          setTimeout(() => {
            window.location.href = '/login'
          }, 800)
          break
        case 403:
          message.error(`权限不足: ${detail}`)
          break
        case 404:
          message.error(`资源不存在: ${detail}`)
          break
        case 422:
          message.error(`参数校验失败: ${detail}`)
          break
        case 429:
          message.error('请求过于频繁，请稍后再试')
          break
        case 500:
        case 502:
        case 503:
        case 504:
          message.error(`服务器错误 (${status}): ${detail}`)
          break
        default:
          message.error(`请求失败 (${status}): ${detail}`)
      }
    } else if (error.request) {
      message.error('网络连接失败，请检查网络或服务器状态')
    } else {
      message.error(`请求异常: ${error.message}`)
    }
    // 网络错误降级
    if (error.code === 'ERR_NETWORK' || error.message?.includes('Network Error')) {
      if (import.meta.env.DEV) {
        console.warn('[NEXUS] API unavailable, using degraded mode');
        return Promise.resolve({ data: null, _degraded: true });
      }
    }
    return Promise.reject(error)
  }
)

export default api

// ==================== Workflow API ====================
export const workflowApi = {
  getList: () => api.get('/workflows'),
  getById: (id: string) => api.get(`/workflows/${id}`),
  create: (payload: any) => api.post('/workflows', payload),
  update: (id: string, payload: any) => api.put(`/workflows/${id}`, payload),
  delete: (id: string) => api.delete(`/workflows/${id}`),
  triggerRun: (id: string, payload?: any) => api.post(`/workflows/${id}/runs`, payload || {}),
}

// ==================== Workflow Run API ====================
export const runApi = {
  getList: (workflowId?: string) =>
    api.get('/runs', { params: workflowId ? { workflow_id: workflowId } : undefined }),
  getById: (id: string) => api.get(`/runs/${id}`),
  cancel: (id: string) => api.post(`/runs/${id}/cancel`),
  getLogs: (id: string) => api.get(`/runs/${id}/logs`),
}

// ==================== Agent API ====================
export const agentApi = {
  getList: () => api.get('/agents'),
  getById: (id: string) => api.get(`/agents/${id}`),
  create: (payload: any) => api.post('/agents', payload),
  update: (id: string, payload: any) => api.put(`/agents/${id}`, payload),
  delete: (id: string) => api.delete(`/agents/${id}`),
}

// ==================== Tool API ====================
export const toolApi = {
  getList: () => api.get('/tools'),
  getById: (id: string) => api.get(`/tools/${id}`),
  create: (payload: any) => api.post('/tools', payload),
  update: (id: string, payload: any) => api.put(`/tools/${id}`, payload),
  delete: (id: string) => api.delete(`/tools/${id}`),
}

// ==================== HITL Task API ====================
export const hitlApi = {
  getList: (params?: { status?: string; run_id?: string }) => api.get('/hitl', { params }),
  getById: (id: string) => api.get(`/hitl/${id}`),
  submit: (id: string, payload: any) => api.post(`/hitl/${id}/submit`, payload),
}

// ==================== Analytics API ====================
export const analyticsApi = {
  getDashboard: () => api.get('/analytics/dashboard'),
  getWorkflowStats: (workflowId: string) => api.get(`/analytics/workflows/${workflowId}`),
}

// ==================== Auth API ====================
export const authApi = {
  login: (data: { email: string; password: string }) =>
    api.post('/auth/login', data),
  me: () => api.get('/auth/me'),
}

// ==================== WebSocket ====================
export function connectWebSocket(runId: string): WebSocket {
  const wsUrl = (import.meta as any).env.VITE_WS_URL || 'ws://localhost:8765'
  const token = localStorage.getItem('nexus_token') || ''
  const ws = new WebSocket(`${wsUrl}/ws/v1/runs/${runId}?token=${token}`)

  ws.onerror = () => {
    message.error('WebSocket 连接失败')
  }

  return ws
}
