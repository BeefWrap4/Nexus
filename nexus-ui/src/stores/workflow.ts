import { defineStore } from 'pinia'
import { ref } from 'vue'
import api from '@/api'
import type { Workflow, WorkflowRun, Agent, Tool } from '@/types'

export const useWorkflowStore = defineStore('workflow', () => {
  const workflows = ref<Workflow[]>([])
  const currentWorkflow = ref<Workflow | null>(null)
  const runs = ref<WorkflowRun[]>([])

  async function fetchWorkflows() {
    const { data } = await api.get('/workflows')
    workflows.value = data
  }

  async function createWorkflow(payload: any) {
    const { data } = await api.post('/workflows', payload)
    workflows.value.unshift(data)
    return data
  }

  async function triggerRun(workflowId: string, payload: any) {
    const { data } = await api.post(`/workflows/${workflowId}/runs`, payload)
    return data
  }

  return { workflows, currentWorkflow, runs, fetchWorkflows, createWorkflow, triggerRun }
})

export const useAgentStore = defineStore('agent', () => {
  const agents = ref<Agent[]>([])

  async function fetchAgents() {
    const { data } = await api.get('/agents')
    agents.value = data
  }

  return { agents, fetchAgents }
})

export const useToolStore = defineStore('tool', () => {
  const tools = ref<Tool[]>([])

  async function fetchTools() {
    const { data } = await api.get('/tools')
    tools.value = data
  }

  return { tools, fetchTools }
})
