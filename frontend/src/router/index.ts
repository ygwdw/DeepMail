// 路由：登录 + 主区（Layout 包裹子页面）；未登录跳 /login
import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { TOKEN_KEY } from '@/api/client'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/Login.vue'),
    meta: { public: true },
  },
  {
    path: '/',
    component: () => import('@/views/Layout.vue'),
    redirect: '/inbox',
    children: [
      { path: 'inbox', name: 'inbox', component: () => import('@/views/Inbox.vue') },
      { path: 'emails/:id', name: 'email-detail', component: () => import('@/views/EmailDetail.vue'), props: true },
      { path: 'compose', name: 'compose', component: () => import('@/views/Compose.vue') },
      { path: 'chat/:sessionId?', name: 'chat', component: () => import('@/views/Chat.vue'), props: true },
      { path: 'memory', name: 'memory', component: () => import('@/views/Memory.vue') },
      { path: 'persona', name: 'persona', component: () => import('@/views/Persona.vue') },
      { path: 'knowledge', name: 'knowledge', component: () => import('@/views/Knowledge.vue') },
      { path: 'settings', name: 'settings', component: () => import('@/views/Settings.vue') },
    ],
  },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to) => {
  const hasToken = Boolean(localStorage.getItem(TOKEN_KEY))
  if (!to.meta.public && !hasToken) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (to.name === 'login' && hasToken) {
    return { name: 'inbox' }
  }
})