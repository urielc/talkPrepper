<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { api, AUDIENCE_LABELS, type AudienceKey, type Study, type TalkDetail } from '../api'
import { talkRoute } from '../router'
import { useLessonStore } from '../stores/lesson'
import { useUiStore } from '../stores/ui'
import AiSidebar from '../components/AiSidebar.vue'
import AskAiButton from '../components/AskAiButton.vue'
import NotesColumn from '../components/NotesColumn.vue'
import ResearchColumn from '../components/ResearchColumn.vue'
import TalkReader from '../components/TalkReader.vue'
import DigestPane from '../components/DigestPane.vue'
import AudienceSelect from '../components/AudienceSelect.vue'
import PonderPane from '../components/PonderPane.vue'
import StudySummary from '../components/StudySummary.vue'

// The workspace shows one lesson: a conference talk (talkId) or a topic study (studyId). Both share the left
// research column, the notes and pins column and Ask AI, keyed by the lesson key; only the center and the
// bottom pane differ.
const props = defineProps<{ talkId?: string; studyId?: number }>()
const lesson = useLessonStore()
const ui = useUiStore()

const talk = ref<TalkDetail | null>(null)
const study = ref<Study | null>(null)
const error = ref<string | null>(null)
const draft = ref('')

/** The lesson key notes, pins and chat are stored under: a talk id or study:<id>. */
const lessonKey = computed(() => (props.studyId ? `study:${props.studyId}` : props.talkId || ''))

watch(
  () => [props.talkId, props.studyId] as const,
  async ([id, sid]) => {
    talk.value = null
    study.value = null
    error.value = null
    try {
      if (sid) {
        const [s] = await Promise.all([api.study(sid), lesson.load(`study:${sid}`)])
        study.value = s
        document.title = `${s.topic} · Lesson Prep`
      } else if (id) {
        const [t] = await Promise.all([api.talk(id), lesson.load(id)])
        talk.value = t
        document.title = `${t.title} · Lesson Prep`
      }
    } catch (e: any) {
      error.value = e.message
    }
  },
  { immediate: true },
)

// Who the lesson is for: the digest's questions and Ask AI are written for this class.
async function setAudience(key: AudienceKey) {
  try {
    const r = await api.setLessonAudience(lessonKey.value, key)
    if (talk.value) talk.value.lesson = { ...talk.value.lesson, audience: r.audience, audience_label: r.audience_label, mine: true }
    if (study.value) {
      study.value = { ...study.value, audience: r.audience, audience_label: r.audience_label }
      if (study.value.summary) ui.toast(`Set for ${AUDIENCE_LABELS[key]}. Regenerate the summary to rewrite it for them.`, 'ok', 4000)
      else ui.toast(`Lesson set for ${AUDIENCE_LABELS[key]}`, 'ok', 1800)
    } else {
      ui.toast(`Lesson set for ${AUDIENCE_LABELS[key]}`, 'ok', 1800)
    }
    await lesson.loadMine()
  } catch (e: any) {
    ui.toast(e.message || 'Could not change the class', 'error')
  }
}

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
  <div v-else-if="!talk && !study" class="muted" style="margin: 1.5rem">Loading…</div>
  <div v-else class="workspace">
    <aside class="research-col">
      <ResearchColumn :talk="talk ?? undefined" :study="study ?? undefined" />
    </aside>

    <section ref="readerCol" class="reader-col" :style="{ '--reader-frac': readerFrac }">
      <div class="reader-pane">
      <StudySummary
        v-if="study"
        :study="study"
        @updated="study = $event"
        @audience="setAudience"
      />
      <template v-else-if="talk">
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
          <AudienceSelect :model-value="talk.lesson.audience" @change="setAudience" />
        </div>
        <div class="row between neighbors small">
          <RouterLink v-if="talk.prev" :to="talkRoute(talk.prev.id)" class="muted">‹ {{ talk.prev.title }}</RouterLink>
          <span v-else></span>
          <RouterLink v-if="talk.next" :to="talkRoute(talk.next.id)" class="muted">{{ talk.next.title }} ›</RouterLink>
        </div>
      </header>
      <TalkReader :talk="talk" :scroll-to="scrollTo" @ask="ask" />
      </template>
      </div>

      <div class="splitter" role="separator" aria-orientation="horizontal" aria-label="Resize talk and digest"
           @pointerdown="startDrag" @pointermove="onDrag" @pointerup="endDrag" @pointercancel="endDrag"></div>

      <div class="digest-pane">
        <PonderPane v-if="study" :study="study" @ask="askRaw" />
        <DigestPane v-else-if="talk" :talk="talk" @goto="goto" @ask="askRaw" />
      </div>
    </section>

    <aside class="notes-col">
      <NotesColumn :talk-id="lessonKey" />
    </aside>

    <AskAiButton />
    <AiSidebar :talk-id="lessonKey" :draft="draft" />
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
  padding: 1.5rem 1.75rem 3rem;
}
.digest-pane {
  overflow: auto;
  padding: 0.75rem 1.75rem 3rem;
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
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem 1rem;
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
    padding-left: 1.5rem;
    padding-right: 1.5rem;
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
