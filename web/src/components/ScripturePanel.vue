<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api, type Lookup, type TalkSummary } from '../api'
import { useLessonStore } from '../stores/lesson'
import { useUiStore } from '../stores/ui'
import TalkListItem from './TalkListItem.vue'

const ui = useUiStore()
const lesson = useLessonStore()
const data = ref<Lookup | null>(null)
const error = ref<string | null>(null)
const loading = ref(false)
const citing = ref<{ total: number; talks: TalkSummary[] } | null>(null)
const showCiting = ref(false)
const wholeChapter = ref(false)

watch(
  () => ui.scriptureRef,
  async (r) => {
    data.value = null
    error.value = null
    citing.value = null
    showCiting.value = false
    wholeChapter.value = false
    if (!r) return
    await load(r)
  },
  { immediate: true },
)

async function load(r: string) {
  loading.value = true
  try {
    data.value = await api.lookup(r)
  } catch (e: any) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

async function openChapter(book: string, chapter: number) {
  loading.value = true
  wholeChapter.value = true
  try {
    data.value = await api.chapter(book, chapter)
  } catch (e: any) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

async function toggleCiting() {
  showCiting.value = !showCiting.value
  if (showCiting.value && !citing.value && data.value) {
    citing.value = await api.lookupTalks(data.value.ref, lesson.talkId || undefined)
  }
}

function pin() {
  if (!data.value) return
  lesson.addPin({ kind: 'scripture', scripture_ref: data.value.ref })
}

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape' && ui.scriptureRef) ui.closeScripture()
}
onMounted(() => document.addEventListener('keydown', onKey))
onBeforeUnmount(() => document.removeEventListener('keydown', onKey))

// When reading a whole chapter, dim verses outside the originally cited range.
function inRange(verse: number): boolean {
  const r = ui.scriptureRef
  if (!r) return true
  const m = r.match(/:(\d+)(?:[–-](\d+))?$/)
  if (!m) return true
  const a = Number(m[1])
  const b = m[2] ? Number(m[2]) : a
  return verse >= a && verse <= b
}
</script>

<template>
  <Transition name="slide">
    <aside v-if="ui.scriptureRef" class="panel" role="dialog" aria-label="Scripture">
      <header class="head">
        <div class="grow">
          <h2 v-if="data">{{ data.ref }}</h2>
          <h2 v-else>{{ ui.scriptureRef }}</h2>
          <div v-if="data" class="talk-meta">{{ data.volume }}</div>
        </div>
        <button class="quiet" @click="ui.closeScripture()" aria-label="Close scripture">Close</button>
      </header>

      <div class="body">
        <div v-if="loading" class="muted">Loading…</div>
        <div v-else-if="error" class="notice error">{{ error }}</div>
        <template v-else-if="data">
          <div class="verses serif">
            <p v-for="v in data.verses" :key="v.verse" :class="{ inrange: !wholeChapter || inRange(v.verse) }">
              <sup>{{ v.verse }}</sup> {{ v.text }}
            </p>
          </div>

          <div class="row wrap tools">
            <button class="small gold" :disabled="lesson.hasPin('scripture', data.ref)" @click="pin">
              {{ lesson.hasPin('scripture', data.ref) ? 'Pinned' : 'Pin passage' }}
            </button>
            <button v-if="!wholeChapter" class="small" @click="openChapter(data.book, data.chapter)">Read whole chapter</button>
            <template v-else>
              <button class="small" :disabled="data.chapter <= 1" @click="openChapter(data!.book, data!.chapter - 1)">Previous chapter</button>
              <button class="small" :disabled="data.chapter >= data.chapters" @click="openChapter(data!.book, data!.chapter + 1)">Next chapter</button>
            </template>
            <button class="small" @click="toggleCiting">
              {{ showCiting ? 'Hide talks citing this' : 'Talks citing this passage' }}
            </button>
          </div>

          <section v-if="showCiting" class="citing">
            <div v-if="!citing" class="muted">Looking up…</div>
            <template v-else>
              <p class="muted small">
                {{ citing.total }} other {{ citing.total === 1 ? 'talk cites' : 'talks cite' }} {{ data.ref }}
              </p>
              <ul class="result-list">
                <li v-for="t in citing.talks" :key="t.id">
                  <TalkListItem :talk="t" :aside="t.mentions && t.mentions > 1 ? `${t.mentions} mentions` : undefined" />
                </li>
              </ul>
            </template>
          </section>
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
.body {
  overflow: auto;
  padding: 1rem 1.25rem 3rem;
}
.verses {
  font-size: 1.08rem;
  line-height: 1.65;
}
.verses p {
  margin: 0 0 0.6em;
}
.verses p:not(.inrange) {
  color: var(--ink-3);
}
.verses sup {
  color: var(--gold-2);
  font-family: var(--sans);
  font-size: 0.7em;
  margin-right: 0.15em;
}
.tools {
  margin-top: 1rem;
  padding-top: 0.75rem;
  border-top: 1px solid var(--rule);
}
.citing {
  margin-top: 1rem;
}
.slide-enter-active,
.slide-leave-active {
  transition: transform 0.2s ease;
}
.slide-enter-from,
.slide-leave-to {
  transform: translateX(100%);
}
</style>
