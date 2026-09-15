<script setup lang="ts">
import { ref } from 'vue'
import { api, type Hit, type Verse } from '../api'

export interface SearchOutcome {
  query: string
  mode: string
  requestedMode: string
  results: Hit[]
  verses: (Verse & { snippet: string })[]
}

const emit = defineEmits<{ (e: 'results', r: SearchOutcome): void }>()

const q = ref('')
const mode = ref<'hybrid' | 'keyword' | 'semantic'>('hybrid')
const yearFrom = ref<number | null>(null)
const yearTo = ref<number | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)
const showYears = ref(false)

async function run() {
  const query = q.value.trim()
  if (!query) return
  loading.value = true
  error.value = null
  try {
    const r = await api.search({
      q: query,
      mode: mode.value,
      years: yearFrom.value || yearTo.value ? [yearFrom.value || 1971, yearTo.value || 2100] : undefined,
      limit: 40,
    })
    emit('results', { query, mode: r.mode, requestedMode: mode.value, results: r.results, verses: r.verses })
  } catch (e: any) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <form class="search" @submit.prevent="run" role="search">
    <div class="bar">
      <input v-model="q" type="search" placeholder="Search talks and scriptures" aria-label="Search talks and scriptures" />
      <button class="primary" type="submit" :disabled="loading || !q.trim()">{{ loading ? '…' : 'Search' }}</button>
    </div>
    <div class="row wrap opts">
      <div class="seg" role="radiogroup" aria-label="Search mode">
        <button v-for="m in ['hybrid', 'keyword', 'semantic'] as const" :key="m" type="button" class="small" :class="{ on: mode === m }" @click="mode = m">
          {{ m === 'hybrid' ? 'Words and meaning' : m === 'keyword' ? 'Exact words' : 'Meaning' }}
        </button>
      </div>
      <button type="button" class="quiet small" @click="showYears = !showYears">{{ showYears ? 'Any year' : 'Years…' }}</button>
      <label v-if="showYears" class="row small muted years">
        <input v-model.number="yearFrom" type="number" min="1971" max="2100" placeholder="from" class="yr" />
        <span>to</span>
        <input v-model.number="yearTo" type="number" min="1971" max="2100" placeholder="to" class="yr" />
      </label>
    </div>
    <p class="hint faint small">Put a phrase in quotes for an exact match. Results open in a side reader.</p>
    <div v-if="error" class="notice error small">{{ error }}</div>
  </form>
</template>

<style scoped>
.search {
  margin-bottom: 0.75rem;
}
.bar {
  display: flex;
  gap: 0.5rem;
}
.opts {
  margin-top: 0.5rem;
  gap: 0.4rem 0.6rem;
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
.years {
  gap: 0.35rem;
}
.yr {
  width: 5rem;
  padding: 0.25rem 0.4rem;
}
.hint {
  margin-top: 0.4rem;
}
</style>
