import { createRouter, createWebHistory } from 'vue-router';

const router = createRouter({
  history: createWebHistory('/'),
  routes: [
    {
      path: '/',
      name: 'home',
      component: () => import('@/views/LandingView.vue'),
    },
    {
      path: '/training',
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
      path: '/result/:sessionId',
      name: 'irt-result',
      component: () => import('@/views/IRTResultView.vue'),
      props: true,
    },
    {
      path: '/cbt/admin',
      name: 'cbt-admin',
      component: () => import('@/views/CBTAdminView.vue'),
    },
    {
      path: '/cbt/t/:token',
      name: 'cbt-dashboard',
      component: () => import('@/views/CBTDashboardView.vue'),
      props: true,
    },
    {
      path: '/cbt/t/:token/task/:patientId',
      name: 'cbt-task',
      component: () => import('@/views/CBTTaskView.vue'),
      props: true,
    },
    {
      path: '/cbt/t/:token/result',
      name: 'cbt-result',
      component: () => import('@/views/CBTResultView.vue'),
      props: true,
    },
    {
      path: '/training/admin',
      redirect: { name: 'cbt-admin' },
    },
    {
      path: '/training/t/:token',
      redirect: to => ({ name: 'cbt-dashboard', params: to.params }),
    },
    {
      path: '/training/t/:token/task/:patientId',
      redirect: to => ({ name: 'cbt-task', params: to.params }),
    },
    {
      path: '/training/t/:token/result',
      redirect: to => ({ name: 'cbt-result', params: to.params }),
    },
  ],
});

export default router;
