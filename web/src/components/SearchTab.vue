<script setup lang="ts">
import { ref } from 'vue'
import { api, type Hit, type Verse } from '../api'
import { useUiStore } from '../stores/ui'
import { useLessonStore } from '../stores/lesson'
import TalkListItem from './TalkListItem.vue'

const props = defineProps<{ initialQuery?: string }>()
const ui = useUiStore()
const lesson = useLessonStore()

const q = ref(props.initialQuery || '')
const mode = ref<'hybrid' | 'keyword' | 'semantic'>('hybrid')
const yearFrom = ref<number | null>(null)
const yearTo = ref<number | null>(null)
const results = ref<Hit[]>([])
const verses = ref<(Verse & { snippet: string })[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
const searched = ref(false)
const effectiveMode = ref('')

async function run() {
  if (!q.value.trim()) return
  loading.value = true
  error.value = null
  try {
    const r = await api.search({
      q: q.value.trim(),
      mode: mode.value,
      years: yearFrom.value || yearTo.value ? [yearFrom.value || 1971, yearTo.value || 2100] : undefined,
      limit: 40,
    })
    results.value = r.results
    verses.value = r.verses
    effectiveMode.value = r.mode
    searched.value = true
  } catch (e: any) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

defineExpose({ setQuery: (s: string) => ((q.value = s), run()) })
</script>

<template>
  <div>
    <form class="searchbar" @submit.prevent="run">
      <input v-model="q" type="search" placeholder="Search talks and scriptures, e.g. covenant belonging or “broken heart”" aria-label="Search" />
      <button class="primary" type="submit" :disabled="loading">Search</button>
    </form>
    <div class="row wrap opts">
      <div class="seg" role="radiogroup" aria-label="Search mode">
        <button v-for="m in ['hybrid', 'keyword', 'semantic'] as const" :key="m" type="button" class="small" :class="{ on: mode === m }" @click="mode = m">
          {{ m === 'hybrid' ? 'Words and meaning' : m === 'keyword' ? 'Exact words' : 'Meaning' }}
        </button>
      </div>
      <label class="row small muted">
        Years
        <input v-model.number="yearFrom" type="number" min="1971" max="2100" placeholder="from" class="yr" />
        <input v-model.number="yearTo" type="number" min="1971" max="2100" placeholder="to" class="yr" />
      </label>
    </div>

    <div v-if="loading" class="muted">Searching…</div>
    <div v-else-if="error" class="notice error">{{ error }}</div>
    <template v-else-if="searched">
      <section v-if="verses.length" class="versehits">
        <h3>Scriptures</h3>
        <ul class="result-list">
          <li v-for="v in verses" :key="v.ref" class="row between">
            <div class="grow">
              <button class="ref" @click="ui.openScripture(v.ref)">{{ v.ref }}</button>
              <div class="serif muted" v-html="v.snippet"></div>
            </div>
            <button class="quiet small" :disabled="lesson.hasPin('scripture', v.ref)" @click="lesson.addPin({ kind: 'scripture', scripture_ref: v.ref })">
              {{ lesson.hasPin('scripture', v.ref) ? 'Pinned' : 'Pin' }}
            </button>
          </li>
        </ul>
      </section>
      <h3 v-if="verses.length">Talks</h3>
      <p v-if="effectiveMode !== mode" class="muted small">Meaning-based search is unavailable until embeddings are built; showing exact-word results.</p>
      <p v-if="!results.length" class="empty">No talks matched. Try fewer words, or switch to “Meaning”.</p>
      <ul v-else class="result-list">
        <li v-for="h in results" :key="h.talk_id">
          <TalkListItem :talk="h.talk!" :snippets="h.snippets" />
        </li>
      </ul>
    </template>
    <p v-else class="empty">Search every conference talk since 1971 and the standard works. Results open in a side reader so you keep your place.</p>
  </div>
</template>

<style scoped>
.searchbar {
  display: flex;
  gap: 0.5rem;
}
.opts {
  margin: 0.6rem 0 1rem;
  justify-content: space-between;
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
.yr {
  width: 5rem;
  padding: 0.25rem 0.4rem;
}
h3 {
  font-size: var(--fs-2);
  margin: 0.75rem 0 0.25rem;
}
.versehits {
  margin-bottom: 0.5rem;
}
</style>
