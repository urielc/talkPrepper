import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from './stores/auth'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'home', component: () => import('./views/LandingView.vue') },
    { path: '/login', name: 'login', component: () => import('./views/LoginView.vue'), meta: { public: true } },
    { path: '/set-password', name: 'set-password', component: () => import('./views/SetPasswordView.vue'), meta: { public: true } },
    { path: '/users', name: 'users', component: () => import('./views/UsersView.vue'), meta: { admin: true } },
    {
      path: '/talk/:conf/:slug',
      name: 'talk',
      component: () => import('./views/WorkspaceView.vue'),
      props: (r) => ({ talkId: `${r.params.conf}/${r.params.slug}` }),
    },
    { path: '/settings', name: 'settings', component: () => import('./views/SettingsView.vue'), meta: { admin: true } },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
  scrollBehavior(to, from, saved) {
    if (saved) return saved
    if (to.name === from.name) return undefined
    return { top: 0 }
  },
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (!auth.loaded) await auth.load()
  if (to.meta.public) return auth.user && to.name === 'login' ? { name: 'home' } : true
  if (!auth.user) return { name: 'login', query: to.fullPath !== '/' ? { next: to.fullPath } : {} }
  if (to.meta.admin && !auth.user.is_admin) return { name: 'home' }
  return true
})

export function talkRoute(talkId: string) {
  const [conf, slug] = talkId.split('/')
  return { name: 'talk', params: { conf, slug } }
}
