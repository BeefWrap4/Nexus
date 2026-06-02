export interface Workflow {
  id: string
  name: string
  description: string
  status: 'draft' | 'active' | 'archived'
  current_version: number
  run_count: number
  created_at: string
}

export interface WorkflowNode {
  id: string
  type: 'start' | 'agent' | 'tool' | 'hitl' | 'condition' | 'parallel' | 'loop' | 'delay' | 'end'
  label: string
  config: Record<string, any>
  position?: { x: number; y: number }
}

export interface WorkflowEdge {
  id: string
  source: string
  target: string
  condition?: string
}

export interface WorkflowRun {
  id: string
  workflow_id: string
  status: 'pending' | 'running' | 'paused' | 'completed' | 'failed' | 'cancelled'
  trigger_type: string
  started_at: string
  completed_at?: string
}

export interface Agent {
  id: string
  name: string
  role: string
  goal: string
  model_config: Record<string, any>
  created_at: string
}

export interface Tool {
  id: string
  name: string
  description: string
  type: string
  status: string
  config?: Record<string, any>
  schema?: Record<string, any>
  source?: 'db' | 'registry'
}

export interface HITLTask {
  id: string
  run_id: string
  node_id: string
  task_type: 'approve' | 'select' | 'input' | 'correct'
  title: string
  status: 'pending' | 'approved' | 'rejected' | 'timeout'
  created_at: string
  context?: Record<string, any>
  options?: { label: string; value: string }[]
}

export interface NodeRun {
  id: string
  node_id: string
  node_type: string
  status: string
  input?: Record<string, any>
  output?: Record<string, any>
  error?: Record<string, any>
  started_at?: string
  completed_at?: string
}
