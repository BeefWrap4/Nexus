import { describe, it, expect, vi } from 'vitest'
import { billingApi } from '../billing'
import api from '../index'

vi.mock('../index', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
  },
}))

describe('billingApi', () => {
  it('exposes getUsage, subscribe, openPortal', () => {
    expect(typeof billingApi.getUsage).toBe('function')
    expect(typeof billingApi.subscribe).toBe('function')
    expect(typeof billingApi.openPortal).toBe('function')
  })

  it('calls the correct endpoints', () => {
    billingApi.getUsage()
    expect(api.get).toHaveBeenCalledWith('/billing/usage')

    billingApi.subscribe('pro')
    expect(api.post).toHaveBeenCalledWith('/billing/subscribe', { plan: 'pro' })

    billingApi.openPortal()
    expect(api.post).toHaveBeenCalledWith('/billing/portal')
  })
})
