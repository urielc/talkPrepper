<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { RouterLink, RouterView } from 'vue-router'
import { api } from './api'
import { useUiStore } from './stores/ui'
import { useLessonStore } from './stores/lesson'
import { useAuthStore } from './stores/auth'
import { talkRoute } from './router'
import TalkDrawer from './components/TalkDrawer.vue'
import ScripturePanel from './components/ScripturePanel.vue'

const ui = useUiStore()
const lesson = useLessonStore()
const auth = useAuthStore()
const indexReady = ref<boolean | null>(null)
const menu = ref<'lessons' | 'account' | null>(null)

onMounted(async () => {
  document.addEventListener('click', closeMenus)
  try {
    const h = await api.health()
    indexReady.value = h.index_ready
  } catch {
    indexReady.value = false
  }
})
onBeforeUnmount(() => document.removeEventListener('click', closeMenus))

function closeMenus(e: MouseEvent) {
  if (!(e.target as HTMLElement).closest('.menu-host')) menu.value = null
}
function toggleMenu(which: 'lessons' | 'account') {
  menu.value = menu.value === which ? null : which
  if (which === 'lessons' && menu.value && !lesson.mineLoaded) lesson.loadMine()
}
function cycleTheme() {
  const next = ui.theme === 'system' ? 'light' : ui.theme === 'light' ? 'dark' : 'system'
  ui.setTheme(next)
}
</script>

<template>
  <div class="shell">
    <header class="topbar no-print">
      <RouterLink to="/" class="brand" aria-label="Lesson Prep home">
        <img src="/mark.svg" alt="" width="26" height="26" />
        <span>Lesson Prep</span>
      </RouterLink>
      <nav v-if="auth.user" class="row">
        <RouterLink to="/" class="navlink">Home</RouterLink>
        <RouterLink to="/lessons" class="navlink">Lesson prep</RouterLink>

        <div class="menu-host">
          <button class="navlink menubtn" :class="{ on: menu === 'lessons' }" @click="toggleMenu('lessons')" aria-haspopup="menu" :aria-expanded="menu === 'lessons'">
            My lessons<span v-if="lesson.mine.length" class="count">{{ lesson.mine.length }}</span>
          </button>
          <div v-if="menu === 'lessons'" class="menu" role="menu">
            <p v-if="!lesson.mine.length" class="muted small pad">Nothing in progress yet.</p>
            <RouterLink v-for="m in lesson.mine" :key="m.talk.id" :to="talkRoute(m.talk.id)" class="item" role="menuitem" @click="menu = null">
              <span class="item-title">{{ m.talk.title }}</span>
              <span class="item-meta">{{ m.talk.speaker }}, {{ m.talk.conference }}</span>
            </RouterLink>
          </div>
        </div>

        <div class="menu-host">
          <button class="navlink menubtn" :class="{ on: menu === 'account' }" @click="toggleMenu('account')" aria-haspopup="menu" :aria-expanded="menu === 'account'">
            {{ auth.user.name || auth.user.email }}
          </button>
          <div v-if="menu === 'account'" class="menu right" role="menu">
            <RouterLink v-if="auth.user.is_admin" to="/settings" class="item" role="menuitem" @click="menu = null">Settings</RouterLink>
            <RouterLink v-if="auth.user.is_admin" to="/users" class="item" role="menuitem" @click="menu = null">Users</RouterLink>
            <RouterLink to="/account" class="item" role="menuitem" @click="menu = null">Change password</RouterLink>
            <button class="item" role="menuitem" @click="cycleTheme">Theme: {{ ui.theme === 'system' ? 'auto' : ui.theme }}</button>
            <button class="item" role="menuitem" @click="auth.logout()">Sign out</button>
          </div>
        </div>
      </nav>
      <nav v-else class="row">
        <button class="quiet small" @click="cycleTheme" :title="`Theme: ${ui.theme}`">
          {{ ui.theme === 'system' ? 'Auto' : ui.theme === 'light' ? 'Light' : 'Dark' }}
        </button>
      </nav>
    </header>

    <div v-if="indexReady === false && auth.user?.is_admin" class="notice error index-warning no-print">
      The talk index has not been built yet. Run <code>python -m server.cli index</code>, or rebuild it from
      <RouterLink to="/settings">Settings</RouterLink>.
    </div>

    <main class="content">
      <RouterView />
    </main>

    <template v-if="auth.user">
      <TalkDrawer />
      <ScripturePanel />
    </template>

    <div class="toasts" aria-live="polite">
      <div v-for="t in ui.toasts" :key="t.id" class="toast" :class="t.kind">{{ t.text }}</div>
    </div>
  </div>
</template>

<style scoped>
.shell {
  min-height: 100%;
  display: flex;
  flex-direction: column;
}
.topbar {
  height: var(--header-h);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 1.25rem;
  border-bottom: 1px solid var(--rule);
  background: var(--paper);
  position: sticky;
  top: 0;
  z-index: 20;
}
.brand {
  display: inline-flex;
  align-items: center;
  gap: 0.6rem;
  font-family: var(--serif);
  font-weight: 600;
  font-size: var(--fs-2);
  color: var(--ink);
}
.brand:hover {
  text-decoration: none;
}
.navlink {
  color: var(--ink-2);
  padding: 0.3rem 0.6rem;
  border-radius: var(--radius);
  border: 0;
  background: transparent;
}
.navlink.router-link-active,
.navlink.on {
  color: var(--blue-2);
  background: var(--blue-soft);
}
.count {
  margin-left: 0.35rem;
  color: var(--gold-2);
  font-size: var(--fs-0);
}
.menu-host {
  position: relative;
}
.menu {
  position: absolute;
  top: calc(100% + 0.35rem);
  left: 0;
  min-width: 260px;
  max-width: 360px;
  background: var(--paper);
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  box-shadow: var(--shadow-pop);
  padding: 0.3rem;
  z-index: 30;
}
.menu.right {
  left: auto;
  right: 0;
  min-width: 180px;
}
.item {
  display: block;
  width: 100%;
  text-align: left;
  padding: 0.45rem 0.6rem;
  border: 0;
  border-radius: var(--radius);
  background: transparent;
  color: var(--ink);
}
.item:hover {
  background: var(--paper-2);
  text-decoration: none;
}
.item-title {
  display: block;
  font-family: var(--serif);
  font-weight: 600;
}
.item-meta {
  display: block;
  color: var(--ink-2);
  font-size: var(--fs-0);
}
.pad {
  padding: 0.45rem 0.6rem;
}
.content {
  flex: 1;
  min-height: 0;
}
.index-warning {
  margin: 1rem 1.25rem 0;
}
.index-warning code {
  font-size: 0.9em;
}
.toasts {
  position: fixed;
  bottom: 1.25rem;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  z-index: 60;
}
.toast {
  background: var(--ink);
  color: var(--paper);
  padding: 0.5rem 0.9rem;
  border-radius: var(--radius);
  box-shadow: var(--shadow-pop);
  font-size: var(--fs-0);
}
.toast.error {
  background: var(--danger);
  color: #fff;
}
.toast.ok {
  background: var(--ok);
  color: #fff;
}
</style>
