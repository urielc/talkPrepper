<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api, type ManualPage } from '../api'
import { useUiStore } from '../stores/ui'

const ui = useUiStore()
const data = ref<ManualPage | null>(null)
const error = ref<string | null>(null)
const loading = ref(false)
const body = ref<HTMLElement | null>(null)

watch(
  () => ui.manualUri,
  async (uri) => {
    data.value = null
    error.value = null
    if (!uri) return
    loading.value = true
    try {
      data.value = await api.manualPage(uri)
      body.value?.scrollTo({ top: 0 })
    } catch (e: any) {
      error.value = e.message
    } finally {
      loading.value = false
    }
  },
  { immediate: true },
)

const AUDIENCE: Record<string, string> = {
  children: 'Children',
  youth: 'Youth',
  adults: 'Adults',
  female: 'Young women and women',
  male: 'Young men and men',
}

function audienceText(tags: string[]): string {
  const ages = tags.filter((t) => t === 'children' || t === 'youth' || t === 'adults').map((t) => AUDIENCE[t])
  if (tags.includes('female')) return tags.includes('youth') ? 'Young Women' : 'Women'
  if (tags.includes('male')) return tags.includes('youth') ? 'Aaronic Priesthood' : 'Men'
  return ages.join(', ')
}

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape' && ui.manualUri) ui.closeManual()
}
onMounted(() => document.addEventListener('keydown', onKey))
onBeforeUnmount(() => document.removeEventListener('keydown', onKey))
</script>

<template>
  <Transition name="slide">
    <aside v-if="ui.manualUri" class="panel" role="dialog" aria-label="Church manual">
      <header class="head">
        <div class="grow">
          <div v-if="data" class="kind">{{ data.kind }}<span v-if="data.audience.length"> · {{ audienceText(data.audience) }}</span></div>
          <h2>{{ data ? data.title : 'Loading…' }}</h2>
          <div v-if="data" class="talk-meta">{{ data.manual }}</div>
        </div>
        <button class="quiet" @click="ui.closeManual()" aria-label="Close manual">Close</button>
      </header>

      <div ref="body" class="body">
        <div v-if="loading && !data" class="muted">Loading…</div>
        <div v-else-if="error" class="notice error">{{ error }}</div>
        <template v-else-if="data">
          <div class="text serif">
            <template v-for="(b, i) in data.blocks" :key="i">
              <h3 v-if="b.h && b.h <= 2">{{ b.text }}</h3>
              <h4 v-else-if="b.h">{{ b.text }}</h4>
              <p v-else>{{ b.text }}</p>
            </template>
          </div>

          <div class="row wrap tools">
            <button class="small" :disabled="!data.prev" :title="data.prev?.title" @click="ui.openManual(data!.prev!.uri)">
              Previous page
            </button>
            <button class="small" :disabled="!data.next" :title="data.next?.title" @click="ui.openManual(data!.next!.uri)">
              Next page
            </button>
            <a class="small" :href="data.url" target="_blank" rel="noopener">Open on churchofjesuschrist.org</a>
          </div>

          <p class="source faint small">{{ data.attribution }}</p>
        </template>
      </div>
    </aside>
  </Transition>
</template>

<style scoped>
.panel {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  width: min(560px, 100vw);
  background: var(--paper);
  border-left: 1px solid var(--rule);
  box-shadow: var(--shadow-pop);
  z-index: 40;
  display: flex;
  flex-direction: column;
}
.head {
  display: flex;
  gap: 1rem;
  align-items: flex-start;
  padding: 1rem 1.25rem 0.75rem;
  border-bottom: 1px solid var(--rule);
}
.head h2 {
  font-size: var(--fs-3);
  line-height: 1.25;
}
.kind {
  color: var(--gold-2);
  font-size: var(--fs-0);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin-bottom: 0.2rem;
}
.body {
  overflow: auto;
  padding: 1rem 1.25rem 3rem;
}
.text {
  font-size: 1.05rem;
  line-height: 1.6;
}
.text p {
  margin: 0 0 0.65em;
}
.text h3,
.text h4 {
  font-family: var(--sans);
}
.text h3 {
  font-size: var(--fs-2);
  margin: 1.2em 0 0.4em;
}
.text h4 {
  font-size: var(--fs-1);
  margin: 1em 0 0.3em;
  color: var(--ink-2);
}
.tools {
  margin-top: 1rem;
  padding-top: 0.75rem;
  border-top: 1px solid var(--rule);
  align-items: center;
}
.source {
  margin-top: 1rem;
  line-height: 1.45;
}
.slide-enter-active,
.slide-leave-active {
  transition: transform 0.2s ease;
}
.slide-enter-from,
.slide-leave-to {
  transform: translateX(100%);
}
@media (prefers-reduced-motion: reduce) {
  .slide-enter-active,
  .slide-leave-active {
    transition: none;
  }
}
</style>
