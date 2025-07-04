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
  ],
});

export default router;