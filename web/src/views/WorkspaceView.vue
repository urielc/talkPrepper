<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { api, type TalkDetail } from '../api'
import { talkRoute } from '../router'
import { useLessonStore } from '../stores/lesson'
import { useUiStore } from '../stores/ui'
import AiSidebar from '../components/AiSidebar.vue'
import AskAiButton from '../components/AskAiButton.vue'
import NotesColumn from '../components/NotesColumn.vue'
import ResearchColumn from '../components/ResearchColumn.vue'
import TalkReader from '../components/TalkReader.vue'
import DigestPane from '../components/DigestPane.vue'

const props = defineProps<{ talkId: string }>()
const lesson = useLessonStore()
const ui = useUiStore()

const talk = ref<TalkDetail | null>(null)
const error = ref<string | null>(null)
const draft = ref('')

watch(
  () => props.talkId,
  async (id) => {
    talk.value = null
    error.value = null
    try {
      const [t] = await Promise.all([api.talk(id), lesson.load(id)])
      talk.value = t
      document.title = `${t.title} · Lesson Prep`
    } catch (e: any) {
      error.value = e.message
    }
  },
  { immediate: true },
)

function ask(text: string) {
  draft.value = `About this passage from the talk:\n\n“${text}”\n\n`
  ui.openAi()
}
function askRaw(text: string) {
  draft.value = text
  ui.openAi()
}

// Jump the reader to a paragraph (re-triggers even for the same index).
const scrollTo = ref<number | null>(null)
async function goto(idx: number) {
  scrollTo.value = null
  await nextTick()
  scrollTo.value = idx
}

// Draggable horizontal split between the talk and its digest; ratio persisted.
const readerFrac = ref(0.6)
try {
  const saved = Number(localStorage.getItem('lp.readerFrac'))
  if (saved > 0.2 && saved < 0.9) readerFrac.value = saved
} catch {
  /* ignore */
}
const readerCol = ref<HTMLElement | null>(null)
let dragging = false
function startDrag(e: PointerEvent) {
  dragging = true
  ;(e.target as HTMLElement).setPointerCapture(e.pointerId)
  document.body.style.cursor = 'row-resize'
}
function onDrag(e: PointerEvent) {
  if (!dragging || !readerCol.value) return
  const r = readerCol.value.getBoundingClientRect()
  readerFrac.value = Math.min(0.9, Math.max(0.2, (e.clientY - r.top) / r.height))
}
function endDrag() {
  if (!dragging) return
  dragging = false
  document.body.style.cursor = ''
  try {
    localStorage.setItem('lp.readerFrac', String(readerFrac.value))
  } catch {
    /* ignore */
  }
}
onBeforeUnmount(endDrag)
</script>

<template>
  <div v-if="error" class="notice error" style="margin: 1.5rem">{{ error }} <RouterLink to="/">Choose another talk</RouterLink></div>
  <div v-else-if="!talk" class="muted" style="margin: 1.5rem">Loading talk…</div>
  <div v-else class="workspace">
    <aside class="research-col">
      <ResearchColumn :talk="talk" />
    </aside>

    <section ref="readerCol" class="reader-col" :style="{ '--reader-frac': readerFrac }">
      <div class="reader-pane">
      <header class="talk-head">
        <nav class="crumbs small">
          <RouterLink to="/">Talks</RouterLink> / <span class="muted">{{ talk.conference }}</span>
        </nav>
        <h1>{{ talk.title }}</h1>
        <div class="byline">
          <span>{{ talk.speaker }}</span>
          <span class="muted">{{ talk.conference }}</span>
          <a :href="talk.url" target="_blank" rel="noopener">Read on churchofjesuschrist.org</a>
        </div>
        <div class="current-row">
          <button v-if="lesson.isMine(talk.id)" class="small gold" @click="lesson.removeMine(talk.id)" title="Remove from my lessons">
            In my lessons ✓
          </button>
          <button v-else class="small" @click="lesson.addMine(talk.id)">Add to my lessons</button>
        </div>
        <div class="row between neighbors small">
          <RouterLink v-if="talk.prev" :to="talkRoute(talk.prev.id)" class="muted">‹ {{ talk.prev.title }}</RouterLink>
          <span v-else></span>
          <RouterLink v-if="talk.next" :to="talkRoute(talk.next.id)" class="muted">{{ talk.next.title }} ›</RouterLink>
        </div>
      </header>
      <TalkReader :talk="talk" :scroll-to="scrollTo" @ask="ask" />
      </div>

      <div class="splitter" role="separator" aria-orientation="horizontal" aria-label="Resize talk and digest"
           @pointerdown="startDrag" @pointermove="onDrag" @pointerup="endDrag" @pointercancel="endDrag"></div>

      <div class="digest-pane">
        <DigestPane :talk="talk" @goto="goto" @ask="askRaw" />
      </div>
    </section>

    <aside class="notes-col">
      <NotesColumn :talk-id="talk.id" />
    </aside>

    <AskAiButton />
    <AiSidebar :talk-id="talk.id" :draft="draft" />
  </div>
</template>

<style scoped>
.workspace {
  display: grid;
  grid-template-columns: var(--research-w) minmax(0, 1fr) var(--notes-w);
  height: calc(100vh - var(--header-h));
}
.research-col,
.reader-col,
.notes-col {
  overflow: auto;
  min-height: 0;
}
.research-col {
  border-right: 1px solid var(--rule);
  padding: 1rem 1.1rem 3rem;
}
.notes-col {
  border-left: 1px solid var(--rule);
  padding: 1rem 1.1rem 3rem;
}
.reader-col {
  display: grid;
  grid-template-rows: minmax(8rem, calc(var(--reader-frac, 0.6) * 100%)) auto minmax(6rem, 1fr);
  overflow: hidden;
  padding: 0;
}
.reader-pane {
  overflow: auto;
  padding: 1.75rem 3rem 3rem;
}
.digest-pane {
  overflow: auto;
  padding: 0.75rem 3rem 3rem;
  background: var(--paper);
}
.splitter {
  height: 9px;
  border-top: 1px solid var(--rule);
  border-bottom: 1px solid var(--rule);
  background: var(--paper-2);
  cursor: row-resize;
  touch-action: none;
  position: relative;
}
.splitter::after {
  content: '';
  position: absolute;
  left: 50%;
  top: 3px;
  width: 44px;
  height: 1px;
  margin-left: -22px;
  background: var(--rule-strong);
}
/* Centre the reading column inside whatever width the grid gives it */
.reader-pane > *,
.digest-pane > * {
  width: 100%;
  max-width: calc(var(--reader-width) * 1.35);
  margin-left: auto;
  margin-right: auto;
}
.reader-pane > * {
  max-width: var(--reader-width);
}
.talk-head {
  margin-bottom: 1.75rem;
}
.crumbs {
  margin-bottom: 0.75rem;
  color: var(--ink-2);
}
h1 {
  font-size: var(--fs-5);
  font-weight: 600;
  letter-spacing: -0.01em;
  line-height: 1.15;
}
.byline {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem 1rem;
  margin-top: 0.6rem;
  font-size: var(--fs-1);
}
.current-row {
  margin-top: 0.75rem;
}
.neighbors {
  margin-top: 1rem;
  padding-top: 0.6rem;
  border-top: 1px solid var(--rule);
  gap: 1rem;
}
.neighbors a {
  max-width: 48%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Two columns + notes band */
@media (max-width: 1399px) {
  .workspace {
    grid-template-columns: var(--research-w) minmax(0, 1fr);
    grid-template-rows: minmax(0, 1fr) auto;
  }
  .notes-col {
    grid-column: 1 / -1;
    border-left: 0;
    border-top: 1px solid var(--rule);
    max-height: 42vh;
  }
  .reader-pane,
  .digest-pane {
    padding-left: 2rem;
    padding-right: 2rem;
  }
}

/* Single column: reader first, then research, then notes */
@media (max-width: 999px) {
  .workspace {
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: none;
    height: auto;
  }
  .research-col,
  .reader-col,
  .notes-col {
    overflow: visible;
    border: 0;
    max-height: none;
    padding: 1.25rem 1.25rem 2rem;
    grid-column: auto;
  }
  .reader-col {
    display: block;
    padding: 0;
  }
  .reader-pane,
  .digest-pane {
    overflow: visible;
    padding: 1.25rem 1.25rem 2rem;
  }
  .splitter {
    display: none;
  }
  .reader-col {
    order: -1;
  }
  .research-col,
  .notes-col {
    border-top: 1px solid var(--rule);
  }
}
</style>
