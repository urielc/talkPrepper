<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  api,
  audienceKey,
  AUDIENCE_LABELS,
  type Audience,
  type Gender,
  type Suggestions,
  type SuggestedTalk,
} from '../api'
import { talkRoute } from '../router'
import { useLessonStore } from '../stores/lesson'
import { useUiStore } from '../stores/ui'
import { safeSnippet } from '../utils/markdown'

const props = defineProps<{ initialTopic?: string }>()

const router = useRouter()
const lesson = useLessonStore()
const ui = useUiStore()

const AUDIENCES: { value: Audience; label: string }[] = [
  { value: 'children', label: 'Children' },
  { value: 'youth', label: 'Teens' },
  { value: 'adults', label: 'Adults' },
]
const GENDERS: { value: Gender; label: string }[] = [
  { value: 'any', label: 'Any' },
  { value: 'male', label: 'Male' },
  { value: 'female', label: 'Female' },
]

const topic = ref(props.initialTopic || '')
const audience = ref<Audience>('adults')
const gender = ref<Gender>('any')
try {
  const saved = JSON.parse(localStorage.getItem('lp.audience') || 'null')
  if (saved && AUDIENCES.some((a) => a.value === saved.audience)) audience.value = saved.audience
  if (saved && GENDERS.some((g) => g.value === saved.gender)) gender.value = saved.gender
} catch {
  /* storage unavailable */
}

const data = ref<Suggestions | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)
const refining = ref(false)
const refineError = ref<string | null>(null)
const reasons = ref<Map<string, string> | null>(null)
const showAll = ref(false)
const opening = ref<string | null>(null)

const key = computed(() => audienceKey(audience.value, gender.value))
const classLabel = computed(() => AUDIENCE_LABELS[key.value])

/** With AI picks: the picks in the model's order, then (on request) the rest. */
const shown = computed<SuggestedTalk[]>(() => {
  const talks = data.value?.talks ?? []
  if (!reasons.value) return talks
  const byId = new Map(talks.map((t) => [t.id, t]))
  const picked = [...reasons.value.keys()].map((id) => byId.get(id)).filter((t): t is SuggestedTalk => !!t)
  if (!showAll.value) return picked
  return [...picked, ...talks.filter((t) => !reasons.value!.has(t.id))]
})

function remember() {
  try {
    localStorage.setItem('lp.audience', JSON.stringify({ audience: audience.value, gender: gender.value }))
  } catch {
    /* ignore */
  }
}

async function run() {
  const t = topic.value.trim()
  if (t.length < 2) return
  remember()
  loading.value = true
  error.value = null
  reasons.value = null
  refineError.value = null
  showAll.value = false
  try {
    data.value = await api.suggest(t, audience.value, gender.value)
    router.replace({ query: { ...router.currentRoute.value.query, topic: t } })
  } catch (e: any) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

function pick(value: Audience | Gender, kind: 'audience' | 'gender') {
  if (kind === 'audience') audience.value = value as Audience
  else gender.value = value as Gender
  if (data.value) run()
  else remember()
}

async function refine() {
  if (!data.value?.talks.length) return
  refining.value = true
  refineError.value = null
  try {
    const r = await api.refineSuggestions(
      data.value.topic,
      audience.value,
      gender.value,
      data.value.talks.slice(0, 30).map((t) => t.id),
    )
    reasons.value = new Map(r.picks.map((p) => [p.talk_id, p.reason]))
    if (!r.picks.length) refineError.value = 'The AI found no strong match among these talks.'
  } catch (e: any) {
    refineError.value = e.message
  } finally {
    refining.value = false
  }
}

/** Starting from a suggestion adds the talk to "my lessons" with this audience, so the
 *  digest and Ask AI are written for the class. */
async function start(t: SuggestedTalk) {
  opening.value = t.id
  try {
    await lesson.addMine(t.id, key.value, true)
    ui.toast(`Added to your lessons for ${classLabel.value}`, 'ok', 2200)
    router.push(talkRoute(t.id))
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
  <div class="suggest">
    <form class="controls" @submit.prevent="run">
      <div class="row">
        <input
          v-model="topic"
          type="search"
          class="grow"
          placeholder="A topic, e.g. forgiveness, ministering, the Sabbath"
          aria-label="Lesson topic"
          maxlength="300"
        />
        <button type="submit" class="primary" :disabled="loading || topic.trim().length < 2">
          {{ loading ? 'Finding…' : 'Suggest' }}
        </button>
      </div>
      <div class="row wrap filters">
        <div class="seg" role="radiogroup" aria-label="Age group">
          <button
            v-for="a in AUDIENCES"
            :key="a.value"
            type="button"
            class="small"
            role="radio"
            :aria-checked="audience === a.value"
            :class="{ on: audience === a.value }"
            @click="pick(a.value, 'audience')"
          >
            {{ a.label }}
          </button>
        </div>
        <div class="seg" role="radiogroup" aria-label="Class">
          <button
            v-for="g in GENDERS"
            :key="g.value"
            type="button"
            class="small"
            role="radio"
            :aria-checked="gender === g.value"
            :class="{ on: gender === g.value }"
            @click="pick(g.value, 'gender')"
          >
            {{ g.label }}
          </button>
        </div>
      </div>
      <p class="faint small for">Lesson for: <strong>{{ classLabel }}</strong></p>
    </form>

    <div v-if="error" class="notice error">{{ error }}</div>
    <template v-else-if="data">
      <p v-if="!data.talks.length" class="empty">No talks found for “{{ data.topic }}”. Try other words.</p>
      <template v-else>
        <div class="row between ai">
          <span class="faint small">
            {{ reasons ? `AI picks for ${classLabel}` : `${data.talks.length} talks, best match first` }}
          </span>
          <button v-if="!reasons" class="small" :disabled="refining" @click="refine">
            {{ refining ? 'Asking AI…' : 'Refine with AI' }}
          </button>
          <button v-else class="quiet small" @click="showAll = !showAll">
            {{ showAll ? 'AI picks only' : 'Show all matches' }}
          </button>
        </div>
        <div v-if="refineError" class="notice error small">{{ refineError }}</div>
        <ol class="plain talks">
          <li v-for="t in shown" :key="t.id">
            <button class="talk" :disabled="opening === t.id" @click="start(t)">
              <span class="talk-title">{{ t.title }}</span>
              <span class="talk-meta">{{ t.speaker }}, {{ t.conference }}</span>
              <span v-if="t.calling" class="calling">{{ t.calling }}</span>
              <span v-if="reasons?.get(t.id)" class="reason">{{ reasons.get(t.id) }}</span>
              <span v-else-if="t.snippet" class="snippet" v-html="safeSnippet(t.snippet)"></span>
            </button>
          </li>
        </ol>
      </template>

      <template v-if="data.manuals.length">
        <h3>Related lessons and manuals</h3>
        <ul class="plain manuals">
          <li v-for="m in data.manuals" :key="m.uri">
            <button class="talk" @click="ui.openManual(m.uri)">
              <span v-if="m.kind !== m.manual" class="kind">{{ m.kind }}</span>
              <span class="talk-title">{{ m.manual }}</span>
              <span class="page-title">{{ m.title }}</span>
            </button>
          </li>
        </ul>
      </template>
      <template v-if="data.songs?.length">
        <h3>Hymns and songs</h3>
        <ul class="plain manuals">
          <li v-for="m in data.songs" :key="m.uri">
            <button class="talk" @click="ui.openManual(m.uri)">
              <span class="talk-title">{{ m.title }}</span>
            </button>
          </li>
        </ul>
      </template>
    </template>
    <p v-else-if="!loading" class="faint small hint">
      Enter a topic and choose who the lesson is for. Talks are ranked from the library; Refine with AI has the
      assistant pick the best ones and say why.
    </p>
  </div>
</template>

<style scoped>
.controls {
  display: grid;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
}
.filters {
  gap: 0.5rem;
}
.for {
  margin: 0;
}
.seg {
  display: inline-flex;
  border: 1px solid var(--rule-strong);
  border-radius: var(--radius);
  overflow: hidden;
}
.seg button {
  border: 0;
  border-radius: 0;
  background: transparent;
}
.seg button + button {
  border-left: 1px solid var(--rule-strong);
}
.seg button.on {
  background: var(--blue);
  color: #fff;
}
.ai {
  margin: 0.25rem 0 0.5rem;
  align-items: center;
}
.plain {
  list-style: none;
  margin: 0;
  padding: 0;
  background: var(--paper);
  border: 1px solid var(--rule);
  border-radius: var(--radius);
}
.talks {
  max-height: 60vh;
  overflow: auto;
}
.plain li + li {
  border-top: 1px solid var(--rule);
}
.talk {
  display: block;
  width: 100%;
  text-align: left;
  padding: 0.55rem 0.7rem;
  border: 0;
  border-radius: 0;
  background: transparent;
  color: inherit;
  font: inherit;
  cursor: pointer;
}
.talk:hover {
  background: var(--paper-2);
}
.talk:hover .talk-title {
  color: var(--blue-2);
}
.talk-title,
.talk-meta,
.page-title,
.calling,
.reason,
.snippet,
.kind {
  display: block;
}
.talk-title {
  font-weight: 600;
}
.talk-meta {
  margin-top: 0.1rem;
}
.page-title {
  margin-top: 0.1rem;
  font-size: var(--fs-0);
  color: var(--ink-2);
}
.calling {
  color: var(--ink-3);
  font-size: var(--fs-0);
}
.reason,
.snippet {
  margin-top: 0.3rem;
  font-size: var(--fs-0);
  line-height: 1.45;
  color: var(--ink-2);
}
.reason {
  border-left: 2px solid var(--gold);
  padding-left: 0.5rem;
}
.snippet {
  display: -webkit-box;
  -webkit-line-clamp: 3;
  line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.kind {
  color: var(--gold-2);
  font-size: var(--fs-0);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
h3 {
  font-size: var(--fs-2);
  margin: 1.25rem 0 0.4rem;
}
.hint {
  line-height: 1.5;
}
</style>
