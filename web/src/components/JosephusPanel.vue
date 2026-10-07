<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api, type JosephusPassage } from '../api'
import { useUiStore } from '../stores/ui'

const ui = useUiStore()
const data = ref<JosephusPassage | null>(null)
const error = ref<string | null>(null)
const loading = ref(false)
const showNotes = ref(false)
// Sections of the reference that was opened, so a whole chapter can dim the rest.
const cited = ref<Set<string>>(new Set())
const wholeChapter = ref(false)

watch(
  () => ui.josephusRef,
  async (r) => {
    data.value = null
    error.value = null
    wholeChapter.value = false
    cited.value = new Set()
    if (!r) return
    const d = await load(r)
    if (d) cited.value = new Set(d.sections.map((s) => s.ref))
  },
  { immediate: true },
)

async function load(r: string): Promise<JosephusPassage | null> {
  loading.value = true
  error.value = null
  try {
    data.value = await api.josephus(r)
    return data.value
  } catch (e: any) {
    error.value = e.message
    return null
  } finally {
    loading.value = false
  }
}

async function openChapter() {
  if (!data.value?.chapter_ref) return
  wholeChapter.value = true
  await load(data.value.chapter_ref)
}

// Previous/next move the reading position, so the new section becomes the cited one.
async function step(r: string | null) {
  if (!r) return
  wholeChapter.value = false
  const d = await load(r)
  if (d) cited.value = new Set(d.sections.map((s) => s.ref))
}

function hasNotes(d: JosephusPassage): boolean {
  return d.sections.some((s) => s.notes.length)
}

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape' && ui.josephusRef) ui.closeJosephus()
}
onMounted(() => document.addEventListener('keydown', onKey))
onBeforeUnmount(() => document.removeEventListener('keydown', onKey))
</script>

<template>
  <Transition name="slide">
    <aside v-if="ui.josephusRef" class="panel" role="dialog" aria-label="Josephus">
      <header class="head">
        <div class="grow">
          <h2>{{ data ? data.ref : ui.josephusRef }}</h2>
          <div v-if="data" class="talk-meta">
            Josephus, {{ data.work_title }}<span class="faint"> (Niese {{ data.niese }})</span>
          </div>
          <div v-if="data?.chapter_title" class="chapter" :title="data.chapter_title">{{ data.chapter_title }}</div>
        </div>
        <button class="quiet" @click="ui.closeJosephus()" aria-label="Close Josephus">Close</button>
      </header>

      <div class="body">
        <div v-if="loading && !data" class="muted">Loading…</div>
        <div v-else-if="error" class="notice error">{{ error }}</div>
        <template v-else-if="data">
          <div class="sections serif">
            <section
              v-for="s in data.sections"
              :key="s.ref"
              :class="{ inrange: !wholeChapter || cited.has(s.ref) }"
            >
              <p v-for="(para, i) in s.text.split('\n\n')" :key="i">
                <sup v-if="i === 0" :title="`Whiston ${s.ref}, Niese ${s.niese}`">{{ s.section }}</sup> {{ para }}
              </p>
              <ol v-if="showNotes && s.notes.length" class="notes">
                <li v-for="(n, k) in s.notes" :key="k">{{ n }}</li>
              </ol>
            </section>
          </div>

          <div class="row wrap tools">
            <button class="small" :disabled="!data.prev" @click="step(data!.prev)">Previous section</button>
            <button class="small" :disabled="!data.next" @click="step(data!.next)">Next section</button>
            <button v-if="data.chapter_ref && !wholeChapter && data.sections.length" class="small" @click="openChapter">
              Read whole chapter
            </button>
            <button v-if="hasNotes(data)" class="small" @click="showNotes = !showNotes">
              {{ showNotes ? "Hide Whiston's notes" : "Show Whiston's notes" }}
            </button>
          </div>

          <p class="source faint small">
            Josephus is a first-century historian, not scripture. Whiston's notes are the translator's own
            18th-century comments. {{ data.attribution }}
          </p>
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
  width: min(520px, 100vw);
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
}
.chapter {
  margin-top: 0.35rem;
  font-family: var(--serif);
  font-style: italic;
  color: var(--ink-2);
  line-height: 1.35;
  /* Whiston's chapter summaries run to five lines; the full text is in the tooltip. */
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.body {
  overflow: auto;
  padding: 1rem 1.25rem 3rem;
}
.sections {
  font-size: 1.08rem;
  line-height: 1.65;
}
.sections p {
  margin: 0 0 0.6em;
}
.sections section:not(.inrange) {
  color: var(--ink-3);
}
.sections sup {
  color: var(--gold-2);
  font-family: var(--sans);
  font-size: 0.7em;
  margin-right: 0.15em;
}
.notes {
  margin: 0 0 1em;
  padding: 0.5rem 0.75rem 0.5rem 1.75rem;
  border-left: 2px solid var(--gold);
  font-family: var(--sans);
  font-size: var(--fs-0);
  line-height: 1.5;
  color: var(--ink-2);
}
.notes li + li {
  margin-top: 0.35em;
}
.tools {
  margin-top: 1rem;
  padding-top: 0.75rem;
  border-top: 1px solid var(--rule);
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
