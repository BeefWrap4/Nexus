import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'

// Mock the billing API so Pricing.vue doesn't touch axios
vi.mock('@/api', () => ({
  billingApi: {
    getUsage: vi.fn(),
    subscribe: vi.fn(),
    openPortal: vi.fn(),
  },
}))

// Stub ant-design-vue components/icons to avoid pulling in the full library
vi.mock('ant-design-vue', () => ({
  message: { error: vi.fn(), success: vi.fn() },
}))

vi.mock('@ant-design/icons-vue', () => ({
  CheckOutlined: { name: 'CheckOutlined', template: '<span class="check-stub" />' },
}))

import Pricing from '../Pricing.vue'

describe('Pricing.vue', () => {
  it('mounts without throwing', () => {
    const wrapper = mount(Pricing, {
      global: {
        stubs: {
          'a-page-header': { template: '<div class="page-header-stub" />' },
          'a-row': { template: '<div class="row-stub"><slot /></div>' },
          'a-col': { template: '<div class="col-stub"><slot /></div>' },
          'a-card': { template: '<div class="card-stub"><slot /></div>' },
          'a-button': {
            template:
              '<button class="btn-stub" @click="$emit(\'click\')"><slot /></button>',
          },
        },
      },
    })
    expect(wrapper.exists()).toBe(true)
  })
})
