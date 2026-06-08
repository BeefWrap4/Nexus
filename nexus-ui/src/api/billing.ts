// ==================== Billing API ====================
import api from './index'

export const billingApi = {
  getUsage: () => api.get('/billing/usage'),
  subscribe: (plan: 'pro' | 'enterprise') =>
    api.post('/billing/subscribe', { plan }),
  openPortal: () => api.post('/billing/portal'),
}
