<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { RouterLink, RouterView } from 'vue-router'
import { api } from './api'
import { useUiStore } from './stores/ui'
import { useLessonStore } from './stores/lesson'
import { talkRoute } from './router'
import TalkDrawer from './components/TalkDrawer.vue'
import ScripturePanel from './components/ScripturePanel.vue'

const ui = useUiStore()
const lesson = useLessonStore()
const indexReady = ref<boolean | null>(null)

onMounted(async () => {
  lesson.loadCurrent().catch(() => {})
  try {
    const h = await api.health()
    indexReady.value = h.index_ready
  } catch {
    indexReady.value = false
  }
})

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
      <nav class="row">
        <RouterLink to="/" class="navlink">Talks</RouterLink>
        <RouterLink v-if="lesson.current" :to="talkRoute(lesson.current.id)" class="navlink current" :title="lesson.current.title">
          Current lesson
        </RouterLink>
        <RouterLink to="/settings" class="navlink">Settings</RouterLink>
        <button class="quiet small" @click="cycleTheme" :title="`Theme: ${ui.theme}`">
          {{ ui.theme === 'system' ? 'Auto' : ui.theme === 'light' ? 'Light' : 'Dark' }}
        </button>
      </nav>
    </header>

    <div v-if="indexReady === false" class="notice error index-warning no-print">
      The talk index has not been built yet. Run <code>python -m server.cli index</code>, or rebuild it from
      <RouterLink to="/settings">Settings</RouterLink>.
    </div>

    <main class="content">
      <RouterView />
    </main>

    <TalkDrawer />
    <ScripturePanel />

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
}
.navlink.current {
  color: var(--gold-2);
}
.navlink.router-link-active {
  color: var(--blue-2);
  background: var(--blue-soft);
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
