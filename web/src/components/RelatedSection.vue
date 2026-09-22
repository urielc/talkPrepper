<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api, type Hit } from '../api'
import TalkListItem from './TalkListItem.vue'

const props = defineProps<{ talkId: string }>()
const emit = defineEmits<{ (e: 'count', n: number): void }>()
const results = ref<Hit[]>([])
const terms = ref<string[]>([])
const semantic = ref(true)
const custom = ref(false)
const loading = ref(false)
const error = ref<string | null>(null)
const decade = ref('')
const speaker = ref('')

/** Hits the reader has expanded. Held in memory only, so a refresh or a new talk starts collapsed. */
const expanded = ref(new Set<string>())
function toggle(id: string) {
  const next = new Set(expanded.value)
  if (!next.delete(id)) next.add(id)
  expanded.value = next
}

/** Editing the match terms re-aims this search only; the talk's own terms are untouched. */
const editing = ref(false)
const draft = ref('')

async function run(override?: string[]) {
  loading.value = true
  error.value = null
  results.value = []
  try {
    const r = await api.related(props.talkId, 40, override)
    results.value = r.results
    terms.value = r.terms
    semantic.value = r.semantic
    custom.value = r.custom
    emit('count', r.results.length)
  } catch (e: any) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

watch(
  () => props.talkId,
  () => {
    editing.value = false
    custom.value = false
    expanded.value = new Set()
    run()
  },
  { immediate: true },
)

function startEdit() {
  draft.value = terms.value.join(', ')
  editing.value = true
}
function matchAgain() {
  const list = draft.value.split(',').map((t) => t.trim()).filter(Boolean)
  if (!list.length) return
  editing.value = false
  run(list)
}
function reset() {
  editing.value = false
  run()
}

const decades = computed(() => {
  const s = new Set<string>()
  for (const h of results.value) if (h.talk?.year) s.add(`${Math.floor(h.talk.year / 10) * 10}s`)
  return [...s].sort()
})

const filtered = computed(() =>
  results.value.filter((h) => {
    if (!h.talk) return false
    if (decade.value && `${Math.floor((h.talk.year || 0) / 10) * 10}s` !== decade.value) return false
    if (speaker.value && !h.talk.speaker.toLowerCase().includes(speaker.value.toLowerCase())) return false
    return true
  }),
)

function aside(h: Hit): string | undefined {
  const parts: string[] = []
  if (h.shared_scriptures) parts.push(`${h.shared_scriptures} shared scripture${h.shared_scriptures === 1 ? '' : 's'}`)
  return parts.join(' ') || undefined
}
</script>

<template>
  <div>
    <div v-if="editing" class="row wrap edit">
      <input
        v-model="draft"
        type="text"
        class="terms-input"
        aria-label="Match terms, comma separated"
        placeholder="covenant, temple, ordinance"
        @keydown.enter.prevent="matchAgain"
        @keydown.esc="editing = false"
      />
      <button type="button" @click="matchAgain">Match again</button>
      <button type="button" class="quiet small" @click="reset">Use the talk's terms</button>
    </div>
    <p v-else-if="terms.length" class="muted small terms">
      Matched on: {{ terms.join(', ') }}
      <span v-if="custom" class="badge">edited</span>
      <button type="button" class="quiet small edit-btn" @click="startEdit">Edit</button>
    </p>

    <div v-if="!semantic && !loading" class="notice small">
      Semantic matching is off because embeddings have not been built. Results use keywords only.
    </div>
    <div class="row wrap filters">
      <select v-model="decade" aria-label="Decade">
        <option value="">All decades</option>
        <option v-for="d in decades" :key="d" :value="d">{{ d }}</option>
      </select>
      <input v-model="speaker" type="search" placeholder="Filter by speaker" aria-label="Filter by speaker" />
    </div>

    <div v-if="loading" class="muted">Finding related talks…</div>
    <div v-else-if="error" class="notice error">{{ error }}</div>
    <p v-else-if="!filtered.length" class="empty">No related talks match these filters.</p>
    <ul v-else class="result-list">
      <li v-for="h in filtered" :key="h.talk_id">
        <div class="score" :style="{ width: Math.round(h.score * 100) + '%' }"></div>
        <TalkListItem
          :talk="h.talk!"
          :snippets="h.snippets"
          :aside="aside(h)"
          collapsible
          :expanded="expanded.has(h.talk_id)"
          @toggle="toggle(h.talk_id)"
        />
      </li>
    </ul>
  </div>
</template>

<style scoped>
.terms {
  margin-bottom: 0.5rem;
}
.edit-btn {
  margin-left: 0.35rem;
}
.badge {
  margin-left: 0.35rem;
  padding: 0 0.3rem;
  border: 1px solid var(--gold);
  border-radius: var(--radius);
  color: var(--gold-2);
  font-size: 0.9em;
}
.edit {
  margin-bottom: 0.5rem;
  gap: 0.35rem;
}
.terms-input {
  flex: 1 1 100%;
  min-width: 0;
}
.filters {
  margin: 0.5rem 0 0.75rem;
}
.filters select {
  width: auto;
}
.filters input {
  flex: 1;
  min-width: 10rem;
}
.score {
  height: 2px;
  background: var(--blue-soft);
  margin-bottom: 0.5rem;
  border-radius: 1px;
}
</style>
