<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  api,
  AUDIENCE_LABELS,
  type AudienceKey,
  type SourceKind,
  type TopicGroup,
  type TopicItem,
  type TopicResults,
} from '../api'
import { studyRoute, talkRoute } from '../router'
import { MAX_SOURCES, useTopicStore } from '../stores/topic'
import { useLessonStore } from '../stores/lesson'
import { useUiStore } from '../stores/ui'
import { safeSnippet } from '../utils/markdown'
import AudienceSelect from './AudienceSelect.vue'
import SummarizeDialog from './SummarizeDialog.vue'

const props = defineProps<{ initialTopic?: string }>()
const emit = defineEmits<{ (e: 'searched', topic: string): void }>()

const router = useRouter()
const lesson = useLessonStore()
const ui = useUiStore()
const topicStore = useTopicStore()

const topic = ref(props.initialTopic || '')
const data = ref<TopicResults | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)
const opening = ref<string | null>(null)

// "Refine with AI", per group: the model picks the best of the group's results and says why. For scriptures
// and the Apocrypha it may also add passages the keyword search missed.
interface RefineState {
  busy: boolean
  error: string | null
  reasons: Map<string, string> | null
  additions: TopicItem[]
  showAll: boolean
}
const newState = (): RefineState => ({ busy: false, error: null, reasons: null, additions: [], showAll: false })
const refineStates = reactive<Record<TopicGroup, RefineState>>({
  talks: newState(),
  manuals: newState(),
  songs: newState(),
  scriptures: newState(),
  josephus: newState(),
  apocrypha: newState(),
})
const stateOf = (g: TopicGroup): RefineState => refineStates[g]

function resetRefine() {
  for (const g of Object.keys(refineStates) as TopicGroup[]) refineStates[g] = newState()
}

async function refine(g: TopicGroup) {
  const d = data.value
  const st = stateOf(g)
  if (!d || (!d[g].length && !isPassageGroup(g))) return
  st.busy = true
  st.error = null
  try {
    const r = await api.refineGroup(d.topic, topicStore.audience, g, d[g].slice(0, 30))
    const reasons = new Map(r.picks.map((p) => [p.ref, p.reason]))
    for (const a of r.additions) reasons.set(a.ref, a.reason)
    st.reasons = reasons
    st.additions = r.additions
    if (!reasons.size) st.error = d[g].length ? 'The AI found no strong match among these results.' : 'The AI found no passages for this topic.'
  } catch (e: any) {
    st.error = e.message
  } finally {
    st.busy = false
  }
}

/** Scripture groups can be filled by the AI even when the word search found nothing. */
function isPassageGroup(g: TopicGroup): boolean {
  return g === 'scriptures' || g === 'apocrypha'
}

/** A group as listed: with AI picks, the picks in the model's order, then any passages it added, then (on
 * request) the rest. */
function shownItems(g: TopicGroup): TopicItem[] {
  const items = data.value ? data.value[g] : []
  const st = refineStates[g]
  if (!st.reasons) return items
  const byRef = new Map([...items, ...st.additions].map((t) => [t.ref, t]))
  const picked = [...st.reasons.keys()].map((r) => byRef.get(r)).filter((t): t is TopicItem => !!t)
  return st.showAll ? [...picked, ...items.filter((t) => !st.reasons!.has(t.ref))] : picked
}

const classLabel = computed(() => AUDIENCE_LABELS[topicStore.audience])

const GROUPS: { key: TopicGroup; title: string; tab: string }[] = [
  { key: 'talks', title: 'Conference talks', tab: 'Talks' },
  { key: 'manuals', title: 'Lessons and manuals', tab: 'Manuals' },
  { key: 'songs', title: 'Hymns and songs', tab: 'Songs' },
  { key: 'scriptures', title: 'Scripture passages', tab: 'Scriptures' },
  { key: 'josephus', title: 'Josephus', tab: 'Josephus' },
  { key: 'apocrypha', title: 'Apocrypha', tab: 'Apocrypha' },
]

// One group shows at a time; a new search opens the first group with results.
const active = ref<TopicGroup>('talks')
const countOf = (g: TopicGroup) => (data.value ? data.value[g].length + refineStates[g].additions.length : 0)
const visibleGroups = computed(() => GROUPS.filter((g) => countOf(g.key) > 0 || isPassageGroup(g.key)))
const activeGroup = computed(() => GROUPS.find((g) => g.key === active.value) ?? GROUPS[0])
const nothingFound = computed(() => !!data.value && GROUPS.every((g) => !data.value![g.key].length))

const KIND_LABEL: Record<SourceKind, string> = {
  talk: 'Talk',
  manual: 'Manual',
  song: 'Song',
  scripture: 'Scripture',
  josephus: 'Josephus',
  apocrypha: 'Apocrypha',
}

async function run() {
  const t = topic.value.trim()
  if (t.length < 2) return
  loading.value = true
  error.value = null
  resetRefine()
  try {
    data.value = await api.topicSearch(t, topicStore.audience)
    if (!data.value[active.value].length) active.value = GROUPS.find((g) => data.value![g.key].length)?.key ?? 'talks'
    emit('searched', t)
  } catch (e: any) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

function onAudience(key: AudienceKey) {
  topicStore.setAudience(key)
  if (data.value) run()
}

const preview = (it: { kind: SourceKind; ref: string }) => ui.openSource(it.kind, it.ref)

// Summarize: creates a study from the queue, or updates the study being edited, then opens it.
const summarizing = ref(false)
const busy = ref(false)
const summarizeError = ref<string | null>(null)
const studyTopic = computed(() => topicStore.editing?.topic || topic.value.trim())
const canSummarize = computed(() => topicStore.queue.length > 0 && studyTopic.value.length >= 2)

async function summarize(modifier: string) {
  busy.value = true
  summarizeError.value = null
  try {
    const sources = topicStore.queue
    let study
    if (topicStore.editing) {
      const id = topicStore.editing.id
      await api.patchStudy(id, { sources, modifier, audience: topicStore.audience })
      study = await api.regenerateStudy(id)
    } else {
      study = await api.createStudy({ topic: studyTopic.value, audience: topicStore.audience, sources, modifier })
      if (study.error) ui.toast(`The study was created, but the summary failed: ${study.error}`, 'error', 6000)
    }
    topicStore.clear()
    topicStore.stopEditing()
    await lesson.loadMine()
    router.push(studyRoute(study.id))
  } catch (e: any) {
    summarizeError.value = e.message
  } finally {
    busy.value = false
  }
}

function queueItem(it: TopicItem) {
  if (!topicStore.add({ kind: it.kind, ref: it.ref, title: titleOf(it) }))
    ui.toast(`A study takes up to ${MAX_SOURCES} sources`, 'error')
}

function titleOf(it: TopicItem): string {
  if (it.kind === 'manual') return it.manual && it.manual !== it.title ? `${it.manual}: ${it.title}` : it.title
  if (it.kind === 'josephus') return it.subtitle || it.title
  return it.title
}

/** Starting from a talk adds it to "my lessons" with this audience (today's flow). */
async function start(t: TopicItem) {
  opening.value = t.ref
  try {
    await lesson.addMine(t.ref, topicStore.audience, true)
    ui.toast(`Added to your lessons for ${classLabel.value}`, 'ok', 2200)
    router.push(talkRoute(t.ref))
  } catch (e: any) {
    ui.toast(e.message || 'Could not open the talk', 'error')
  } finally {
    opening.value = null
  }
}

onMounted(() => {
  if (topic.value.trim()) run()
})
</script>

<template>
  <div class="topic">
    <form class="controls" @submit.prevent="run">
      <AudienceSelect :model-value="topicStore.audience" title="Who the lesson is for" @change="onAudience" />
      <input
        v-model="topic"
        type="search"
        class="grow"
        placeholder="A topic, e.g. forgiveness, ministering, the Sabbath"
        aria-label="Topic"
        maxlength="300"
      />
      <button type="submit" class="primary" :disabled="loading || topic.trim().length < 2">
        {{ loading ? 'Searching…' : 'Search' }}
      </button>
    </form>

    <div class="layout">
      <main class="results-col">
        <div v-if="error" class="notice error">{{ error }}</div>
        <p v-else-if="nothingFound" class="empty">Nothing found for “{{ data!.topic }}”. Try other words.</p>
        <template v-else-if="data">
          <div class="tabs" role="tablist" aria-label="Kinds of sources">
            <button
              v-for="g in visibleGroups"
              :key="g.key"
              type="button"
              role="tab"
              :id="`tab-${g.key}`"
              :aria-selected="active === g.key"
              :aria-controls="`panel-${g.key}`"
              :class="{ on: active === g.key }"
              @click="active = g.key"
            >
              {{ g.tab }} <span class="count">{{ countOf(g.key) }}</span>
            </button>
          </div>

          <section :id="`panel-${active}`" role="tabpanel" :aria-labelledby="`tab-${active}`" class="panel">
            <div class="panel-head">
              <h2>{{ activeGroup.title }}</h2>
              <button v-if="!stateOf(active).reasons" class="small" :disabled="stateOf(active).busy" @click="refine(active)">
                {{ stateOf(active).busy ? 'Asking AI…' : data[active].length ? 'Refine with AI' : 'Find with AI' }}
              </button>
              <button v-else class="quiet small" @click="stateOf(active).showAll = !stateOf(active).showAll">
                {{ stateOf(active).showAll ? 'AI picks only' : 'Show all matches' }}
              </button>
            </div>
            <div v-if="stateOf(active).error" class="notice error small">{{ stateOf(active).error }}</div>
            <p v-if="!data[active].length && !stateOf(active).additions.length" class="empty small">
              No verses matched these words. Use Find with AI to have it suggest passages.
            </p>
            <ul class="grid">
              <li v-for="it in shownItems(active)" :key="it.ref" class="result" :class="{ queued: topicStore.has(it.kind, it.ref) }">
                <div class="body">
                  <span v-if="it.kind === 'manual' && it.manual_kind && it.manual_kind !== it.manual" class="kicker">{{ it.manual_kind }}</span>
                  <span class="result-title">{{ it.kind === 'manual' ? it.manual : it.title }}</span>
                  <span v-if="it.kind === 'talk'" class="meta">{{ it.speaker }}, {{ it.conference }}</span>
                  <span v-else-if="it.kind === 'manual'" class="meta">{{ it.title }}</span>
                  <span v-else-if="it.kind === 'josephus'" class="meta">{{ it.subtitle }}</span>
                  <span v-if="it.calling" class="meta">{{ it.calling }}</span>
                  <span v-if="refineStates[active].reasons?.get(it.ref)" class="reason">{{ refineStates[active].reasons!.get(it.ref) }}</span>
                  <span v-else-if="it.snippet" class="snippet" v-html="safeSnippet(it.snippet)"></span>
                </div>
                <div class="actions">
                  <button class="small" @click="preview(it)">Preview</button>
                  <button
                    class="small"
                    :class="{ gold: topicStore.has(it.kind, it.ref) }"
                    :disabled="topicStore.has(it.kind, it.ref)"
                    @click="queueItem(it)"
                  >
                    {{ topicStore.has(it.kind, it.ref) ? 'Queued ✓' : 'Queue' }}
                  </button>
                  <button v-if="it.kind === 'talk'" class="quiet small" :disabled="opening === it.ref" @click="start(it)">
                    Use as the lesson
                  </button>
                </div>
              </li>
            </ul>
          </section>
        </template>
        <p v-else-if="!loading" class="hint">
          Choose who it is for, then enter a topic. Results come back by kind: talks, manuals, songs, scriptures,
          Josephus and the Apocrypha. Preview any of them and queue the ones to build on.
        </p>
      </main>

      <aside class="tray" :class="{ idle: !topicStore.queue.length && !topicStore.editing }" aria-label="Queued sources">
        <p v-if="topicStore.editing" class="faint small editing">
          Editing the sources of “{{ topicStore.editing.topic }}”.
          <button class="quiet small" @click="topicStore.stopEditing()">Stop editing</button>
        </p>
        <div class="tray-head">
          <h2>Queued <span class="count">{{ topicStore.queue.length }} of {{ MAX_SOURCES }}</span></h2>
          <button v-if="topicStore.queue.length" class="quiet small" @click="topicStore.clear()">Clear</button>
        </div>
        <p v-if="!topicStore.queue.length" class="faint small tray-empty">
          Nothing queued yet. Queued sources become the basis of a study: an AI summary, things to ponder and further
          material.
        </p>
        <ol v-else class="queue">
          <li v-for="(s, i) in topicStore.queue" :key="s.kind + s.ref" class="queued-item">
            <span class="kind">{{ KIND_LABEL[s.kind] }}</span>
            <button class="link title" :title="s.title" @click="preview(s)">{{ s.title }}</button>
            <span class="ops">
              <button class="quiet small" :disabled="i === 0" :aria-label="`Move ${s.title} up`" @click="topicStore.move(i, -1)">↑</button>
              <button class="quiet small" :disabled="i === topicStore.queue.length - 1" :aria-label="`Move ${s.title} down`" @click="topicStore.move(i, 1)">↓</button>
              <button class="quiet small" :aria-label="`Remove ${s.title}`" @click="topicStore.remove(i)">✕</button>
            </span>
          </li>
        </ol>
        <button class="primary summarize" :disabled="!canSummarize" @click="summarizing = true">
          {{ topicStore.editing ? 'Update summary' : 'Summarize' }}
        </button>
      </aside>
    </div>

    <SummarizeDialog
      v-if="summarizing"
      :mode="topicStore.editing ? 'update' : 'create'"
      :initial-modifier="topicStore.editing?.modifier"
      :busy="busy"
      :error="summarizeError"
      @submit="summarize"
      @close="summarizing = false"
    />
  </div>
</template>

<style scoped>
.controls {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.6rem;
  margin-bottom: 1.25rem;
}
.controls .grow {
  flex: 1 1 18rem;
  min-width: 0;
}
.results-col {
  min-width: 0;
}
.layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) clamp(280px, 24vw, 360px);
  gap: 1.75rem;
  align-items: start;
}

/* tabs: one per kind of source, with how many results it holds */
.tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem;
  border-bottom: 1px solid var(--rule-strong);
}
.tabs button {
  border: 1px solid transparent;
  border-bottom: 0;
  border-radius: var(--radius) var(--radius) 0 0;
  background: transparent;
  color: var(--ink-2);
  padding: 0.45rem 0.85rem;
  margin-bottom: -1px;
  font: inherit;
  cursor: pointer;
}
.tabs button:hover {
  color: var(--ink);
}
.tabs button.on {
  background: var(--paper);
  border-color: var(--rule-strong);
  color: var(--blue);
  font-weight: 600;
}
.count {
  font-size: var(--fs-0);
  font-weight: 400;
  color: var(--ink-3);
  margin-left: 0.15rem;
}
.panel-head,
.tray-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.75rem;
}
.panel-head {
  margin: 1rem 0 0.75rem;
}
h2 {
  font-size: var(--fs-3);
  margin: 0;
}
.grid {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 19rem), 1fr));
  gap: 0.75rem;
}
.result {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: 0.6rem;
  padding: 0.75rem 0.85rem;
  background: var(--paper);
  border: 1px solid var(--rule);
  border-radius: var(--radius);
}
.result.queued {
  border-color: var(--gold);
  box-shadow: inset 3px 0 0 var(--gold);
}
.body > span {
  display: block;
}
.result-title {
  font-weight: 600;
  line-height: 1.3;
}
.meta {
  margin-top: 0.15rem;
  font-size: var(--fs-0);
  color: var(--ink-2);
}
.snippet,
.reason {
  margin-top: 0.4rem;
  font-size: var(--fs-0);
  line-height: 1.45;
  color: var(--ink-2);
}
.snippet {
  display: -webkit-box;
  -webkit-line-clamp: 4;
  line-clamp: 4;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.reason {
  border-left: 2px solid var(--gold);
  padding-left: 0.5rem;
}
.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
}
.kind,
.kicker {
  color: var(--gold-2);
  font-size: var(--fs-0);
  flex-shrink: 0;
}
.hint {
  max-width: 38rem;
  line-height: 1.55;
  color: var(--ink-2);
}

/* the queue stays in view while the results scroll */
.tray {
  position: sticky;
  top: calc(var(--header-h) + 1rem);
  max-height: calc(100vh - var(--header-h) - 2rem);
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
  padding: 0.9rem 1rem 1rem;
  background: var(--paper-2);
  border: 1px solid var(--rule);
  border-radius: var(--radius);
}
.tray-empty,
.editing {
  margin: 0;
  line-height: 1.5;
}
.queue {
  margin: 0;
  padding: 0;
  list-style: none;
}
.queued-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  column-gap: 0.4rem;
  padding: 0.4rem 0;
  border-top: 1px solid var(--rule);
}
.queued-item .kind {
  grid-column: 1;
}
.queued-item .title {
  grid-column: 1;
  text-align: left;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.queued-item .ops {
  grid-column: 2;
  grid-row: 1 / span 2;
  align-self: center;
  display: flex;
  gap: 0.1rem;
}
.link {
  border: 0;
  background: transparent;
  padding: 0;
  color: var(--blue-2);
  font: inherit;
  cursor: pointer;
}
.summarize {
  width: 100%;
}

@media (max-width: 860px) {
  .layout {
    grid-template-columns: minmax(0, 1fr);
  }
  /* on a phone the queue comes first, so Summarize is reachable without scrolling past every result */
  .tray {
    position: static;
    max-height: none;
    order: -1;
  }
  .tray.idle {
    display: none;
  }
  /* one swipeable row of tabs instead of a wrapped second row */
  .tabs {
    flex-wrap: nowrap;
    overflow-x: auto;
    scrollbar-width: none;
  }
  .tabs button {
    flex-shrink: 0;
  }
}
</style>
