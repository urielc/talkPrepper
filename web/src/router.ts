import { createRouter, createWebHistory } from 'vue-router'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'home', component: () => import('./views/HomeView.vue') },
    {
      path: '/talk/:conf/:slug',
      name: 'talk',
      component: () => import('./views/WorkspaceView.vue'),
      props: (r) => ({ talkId: `${r.params.conf}/${r.params.slug}` }),
    },
    { path: '/settings', name: 'settings', component: () => import('./views/SettingsView.vue') },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
  scrollBehavior(to, from, saved) {
    if (saved) return saved
    if (to.name === from.name) return undefined
    return { top: 0 }
  },
})

export function talkRoute(talkId: string) {
  const [conf, slug] = talkId.split('/')
  return { name: 'talk', params: { conf, slug } }
}
