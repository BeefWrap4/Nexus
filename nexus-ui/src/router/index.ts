import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    redirect: '/workflows',
  },
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/Login.vue'),
  },
  {
    path: '/',
    component: () => import('@/views/Layout.vue'),
    children: [
      {
        path: 'dashboard',
        name: 'Dashboard',
        component: () => import('@/views/Dashboard.vue'),
      },
      {
        path: 'workflows',
        name: 'Workflows',
        component: () => import('@/views/Workflows.vue'),
      },
      {
        path: 'workflows/:id/edit',
        name: 'WorkflowEditor',
        component: () => import('@/views/WorkflowEditor.vue'),
      },
      {
        path: 'workflows/:id/runs',
        name: 'WorkflowRuns',
        component: () => import('@/views/WorkflowRuns.vue'),
      },
      {
        path: 'agents',
        name: 'Agents',
        component: () => import('@/views/Agents.vue'),
      },
      {
        path: 'tools',
        name: 'Tools',
        component: () => import('@/views/Tools.vue'),
      },
      {
        path: 'mcp',
        name: 'MCPManager',
        component: () => import('@/views/MCPManager.vue'),
      },
      {
        path: 'runs/:id',
        name: 'RunMonitor',
        component: () => import('@/views/RunMonitor.vue'),
      },
      {
        path: 'hitl',
        name: 'HITLTasks',
        component: () => import('@/views/HITLTasks.vue'),
      },
      {
        path: 'analytics',
        name: 'Analytics',
        component: () => import('@/views/Analytics.vue'),
      },
      {
        path: 'prompts',
        name: 'PromptEditor',
        component: () => import('@/views/PromptEditor.vue'),
      },
      {
        path: 'traces',
        name: 'TraceViewer',
        component: () => import('@/views/TraceViewer.vue'),
      },
      {
        path: 'experiments',
        name: 'PromptExperiments',
        component: () => import('@/views/PromptExperiments.vue'),
      },
      {
        path: 'evals',
        name: 'EvalDashboard',
        component: () => import('@/views/EvalDashboard.vue'),
      },
      {
        path: 'code-review',
        name: 'CodeReview',
        component: () => import('@/views/CodeReview.vue'),
      },
      {
        path: 'pr-bot',
        name: 'PRBotConfig',
        component: () => import('@/views/PRBotConfig.vue'),
      },
      {
        path: 'settings',
        name: 'Settings',
        component: () => import('@/views/Settings.vue'),
      },
    ],
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router