<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api, type Hit } from '../api'
import TalkListItem from './TalkListItem.vue'

const props = defineProps<{ talkId: string }>()
const emit = defineEmits<{ (e: 'count', n: number): void }>()
const results = ref<Hit[]>([])
const terms = ref<string[]>([])
const semantic = ref(true)
const loading = ref(false)
const error = ref<string | null>(null)
const decade = ref('')
const speaker = ref('')

watch(
  () => props.talkId,
  async (id) => {
    loading.value = true
    error.value = null
    results.value = []
    try {
      const r = await api.related(id, 40)
      results.value = r.results
      terms.value = r.terms
      semantic.value = r.semantic
      emit('count', r.results.length)
    } catch (e: any) {
      error.value = e.message
    } finally {
      loading.value = false
    }
  },
  { immediate: true },
)

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
    <p v-if="terms.length" class="muted small terms">Matched on: {{ terms.join(', ') }}</p>
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
        <TalkListItem :talk="h.talk!" :snippets="h.snippets" :aside="aside(h)" />
      </li>
    </ul>
  </div>
</template>

<style scoped>
.terms {
  margin-bottom: 0.5rem;
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
