import { createRouter, createWebHistory } from 'vue-router';

const router = createRouter({
  history: createWebHistory('/'),
  routes: [
    {
      path: '/',
      name: 'chat',
      component: () => import('@/views/ChatView.vue'),
    },
    {
      path: '/history',
      name: 'history',
      component: () => import('@/views/HistoryView.vue'),
    },
    {
      path: '/history/:sessionId',
      name: 'history-detail',
      component: () => import('@/views/HistoryDetailView.vue'),
      props: true,
    },
    {
      path: '/debriefing/:sessionId?',
      name: 'debriefing',
      component: () => import('@/views/DebriefingView.vue'),
      props: true,
    },
    {
      path: '/prompts',
      name: 'prompts',
      component: () => import('@/views/PromptManagementView.vue'),
    },
    {
      path: '/irt',
      name: 'irt',
      component: () => import('@/views/IRTManagementView.vue'),
    },
    {
      path: '/training/admin',
      name: 'cbt-admin',
      component: () => import('@/views/CBTAdminView.vue'),
    },
    {
      path: '/training/t/:token',
      name: 'cbt-dashboard',
      component: () => import('@/views/CBTDashboardView.vue'),
      props: true,
    },
    {
      path: '/training/t/:token/task/:patientId',
      name: 'cbt-task',
      component: () => import('@/views/CBTTaskView.vue'),
      props: true,
    },
    {
      path: '/training/t/:token/result',
      name: 'cbt-result',
      component: () => import('@/views/CBTResultView.vue'),
      props: true,
    },
  ],
});

export default router;