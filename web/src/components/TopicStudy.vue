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

const GROUPS: { key: TopicGroup; title: string }[] = [
  { key: 'talks', title: 'Conference talks' },
  { key: 'manuals', title: 'Lessons and manuals' },
  { key: 'songs', title: 'Hymns and songs' },
  { key: 'scriptures', title: 'Scripture passages' },
  { key: 'josephus', title: 'Josephus' },
  { key: 'apocrypha', title: 'Apocrypha' },
]

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
    router.replace({ query: { ...router.currentRoute.value.query, topic: t } })
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
      <div class="row">
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
      </div>
    </form>

    <p v-if="topicStore.editing && !topicStore.queue.length" class="notice small">
      Editing the sources of “{{ topicStore.editing.topic }}”. Queue some sources, then update the summary.
      <button class="quiet small" @click="topicStore.stopEditing()">Stop editing</button>
    </p>
    <section v-if="topicStore.queue.length" class="tray" aria-label="Queued sources">
      <p v-if="topicStore.editing" class="faint small">Editing the sources of “{{ topicStore.editing.topic }}”.</p>
      <div class="row between">
        <h3>Queued ({{ topicStore.queue.length }} of {{ MAX_SOURCES }})</h3>
        <button class="quiet small" @click="topicStore.clear()">Clear</button>
      </div>
      <ol class="plain queue">
        <li v-for="(s, i) in topicStore.queue" :key="s.kind + s.ref" class="queued">
          <span class="kind">{{ KIND_LABEL[s.kind] }}</span>
          <button class="link title" @click="preview(s)">{{ s.title }}</button>
          <span class="row ops">
            <button class="quiet small" :disabled="i === 0" :aria-label="`Move ${s.title} up`" @click="topicStore.move(i, -1)">↑</button>
            <button class="quiet small" :disabled="i === topicStore.queue.length - 1" :aria-label="`Move ${s.title} down`" @click="topicStore.move(i, 1)">↓</button>
            <button class="quiet small" :aria-label="`Remove ${s.title}`" @click="topicStore.remove(i)">Remove</button>
          </span>
        </li>
      </ol>
      <div class="row between summarize">
        <button v-if="topicStore.editing" class="quiet small" @click="topicStore.stopEditing()">
          Stop editing “{{ topicStore.editing.topic }}”
        </button>
        <span v-else></span>
        <button class="primary" :disabled="!canSummarize" @click="summarizing = true">
          {{ topicStore.editing ? 'Update summary' : 'Summarize' }}
        </button>
      </div>
    </section>
    <SummarizeDialog
      v-if="summarizing"
      :mode="topicStore.editing ? 'update' : 'create'"
      :initial-modifier="topicStore.editing?.modifier"
      :busy="busy"
      :error="summarizeError"
      @submit="summarize"
      @close="summarizing = false"
    />

    <div v-if="error" class="notice error">{{ error }}</div>
    <template v-else-if="data">
      <template v-for="g in GROUPS" :key="g.key">
        <template v-if="data[g.key].length || isPassageGroup(g.key)">
          <div class="row between group-head">
            <h3>{{ g.title }}</h3>
            <button v-if="!stateOf(g.key).reasons" class="small" :disabled="stateOf(g.key).busy" @click="refine(g.key)">
              {{ stateOf(g.key).busy ? 'Asking AI…' : data[g.key].length ? 'Refine with AI' : 'Find with AI' }}
            </button>
            <button v-else class="quiet small" @click="stateOf(g.key).showAll = !stateOf(g.key).showAll">
              {{ stateOf(g.key).showAll ? 'AI picks only' : 'Show all matches' }}
            </button>
          </div>
          <div v-if="stateOf(g.key).error" class="notice error small">{{ stateOf(g.key).error }}</div>
          <p v-if="!data[g.key].length && !stateOf(g.key).additions?.length" class="empty small">No verses matched these words. The AI can suggest passages.</p>
          <ul class="plain results" :class="{ scroll: g.key === 'talks' }">
            <li v-for="it in shownItems(g.key)" :key="it.ref" class="result">
              <div class="body">
                <span v-if="it.kind === 'manual' && it.manual_kind && it.manual_kind !== it.manual" class="kicker">{{ it.manual_kind }}</span>
                <span class="result-title">{{ it.kind === 'manual' ? it.manual : it.title }}</span>
                <span v-if="it.kind === 'talk'" class="meta">{{ it.speaker }}, {{ it.conference }}</span>
                <span v-else-if="it.kind === 'manual'" class="meta">{{ it.title }}</span>
                <span v-else-if="it.kind === 'josephus'" class="meta">{{ it.subtitle }}</span>
                <span v-if="it.calling" class="meta">{{ it.calling }}</span>
                <span v-if="refineStates[g.key].reasons?.get(it.ref)" class="reason">{{ refineStates[g.key].reasons!.get(it.ref) }}</span>
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
        </template>
      </template>
      <p v-if="GROUPS.every((g) => !data![g.key].length)" class="empty">Nothing found for “{{ data.topic }}”. Try other words.</p>
    </template>
    <p v-else-if="!loading" class="faint small hint">
      Choose who it is for, then enter a topic. Preview any result and queue the ones to build on. Queued sources
      become the basis of a study, with an AI summary, questions and further material.
    </p>
  </div>
</template>

<style scoped>
.controls {
  display: grid;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
}
.summarize {
  margin-top: 0.6rem;
}
.tray {
  border: 1px solid var(--rule-strong);
  border-radius: var(--radius);
  background: var(--paper);
  padding: 0.5rem 0.7rem 0.7rem;
  margin-bottom: 0.75rem;
}
.tray h3 {
  margin: 0.2rem 0 0.4rem;
}
.plain {
  list-style: none;
  margin: 0;
  padding: 0;
}
.plain li + li {
  border-top: 1px solid var(--rule);
}
.queued {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.3rem 0;
}
.queued .title {
  flex: 1;
  min-width: 0;
  text-align: left;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.link {
  border: 0;
  background: transparent;
  padding: 0;
  color: var(--blue-2);
  font: inherit;
  cursor: pointer;
}
.ops {
  flex-shrink: 0;
  gap: 0.15rem;
}
.kind,
.kicker {
  color: var(--gold-2);
  font-size: var(--fs-0);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  flex-shrink: 0;
}
.results {
  background: var(--paper);
  border: 1px solid var(--rule);
  border-radius: var(--radius);
}
.results.scroll {
  max-height: 50vh;
  overflow: auto;
}
.result {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  padding: 0.55rem 0.7rem;
}
.body > span {
  display: block;
}
.result-title {
  font-weight: 600;
}
.meta {
  margin-top: 0.1rem;
  font-size: var(--fs-0);
  color: var(--ink-2);
}
.snippet {
  margin-top: 0.3rem;
  font-size: var(--fs-0);
  line-height: 1.45;
  color: var(--ink-2);
  display: -webkit-box;
  -webkit-line-clamp: 3;
  line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
}
h3 {
  font-size: var(--fs-2);
  margin: 1.1rem 0 0.4rem;
}
.group-head {
  align-items: flex-end;
}
.reason {
  margin-top: 0.3rem;
  font-size: var(--fs-0);
  line-height: 1.45;
  color: var(--ink-2);
  border-left: 2px solid var(--gold);
  padding-left: 0.5rem;
}
.hint {
  line-height: 1.5;
}
</style>
