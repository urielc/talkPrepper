<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { api, type Conference, type TalkSummary } from '../api'
import { talkRoute } from '../router'

const conferences = ref<Conference[]>([])
const conferenceId = ref('')
const talks = ref<TalkSummary[]>([])
const q = ref('')
const allConferences = ref(false)
const results = ref<TalkSummary[] | null>(null)
const recent = ref<{ talk: TalkSummary; updated_at: string; notes_len: number; pin_count: number; chat_count: number }[]>([])
const loading = ref(false)
const error = ref<string | null>(null)

onMounted(async () => {
  try {
    conferences.value = await api.conferences()
    if (conferences.value.length) conferenceId.value = conferences.value[0].id
    recent.value = await api.lessons()
  } catch (e: any) {
    error.value = e.message
  }
})

watch(conferenceId, async (id) => {
  if (!id) return
  loading.value = true
  try {
    talks.value = await api.conferenceTalks(id)
  } finally {
    loading.value = false
  }
})

let timer: ReturnType<typeof setTimeout> | null = null
watch([q, allConferences], () => {
  if (timer) clearTimeout(timer)
  if (!q.value.trim()) {
    results.value = null
    return
  }
  timer = setTimeout(async () => {
    results.value = await api.talks(q.value.trim(), allConferences.value ? undefined : conferenceId.value, 60)
  }, 180)
})

const shown = computed(() => results.value ?? talks.value)
const current = computed(() => conferences.value.find((c) => c.id === conferenceId.value))
</script>

<template>
  <div class="home">
    <section class="pick">
      <h1>Which talk are you teaching?</h1>
      <p class="muted lede">
        Choose the assigned talk to open a workspace with the full text, related talks, every scripture it cites, search, an AI
        assistant, and your notes.
      </p>

      <div class="controls">
        <select v-model="conferenceId" aria-label="Conference">
          <option v-for="c in conferences" :key="c.id" :value="c.id">{{ c.label }} ({{ c.talk_count }})</option>
        </select>
        <input v-model="q" type="search" placeholder="Speaker or title" aria-label="Find a talk" />
        <label class="row small muted"><input v-model="allConferences" type="checkbox" /> All conferences</label>
      </div>

      <div v-if="error" class="notice error">{{ error }}</div>
      <div v-else-if="loading && !shown.length" class="muted">Loading…</div>
      <p v-else-if="!shown.length" class="empty">No talks match. Try another spelling, or tick “All conferences”.</p>
      <ol v-else class="talks">
        <li v-for="t in shown" :key="t.id">
          <RouterLink :to="talkRoute(t.id)" class="talk">
            <span class="talk-title">{{ t.title }}</span>
            <span class="talk-meta">
              {{ t.speaker }}<template v-if="results">, {{ t.conference }}</template>
              <span v-if="t.has_lesson" class="badge">notes</span>
            </span>
          </RouterLink>
        </li>
      </ol>
      <p v-if="current && !results" class="faint small">
        {{ current.label }} <a :href="current.url" target="_blank" rel="noopener">on churchofjesuschrist.org</a>
      </p>
    </section>

    <aside v-if="recent.length" class="recent">
      <h2>Recent lessons</h2>
      <ul>
        <li v-for="r in recent" :key="r.talk.id">
          <RouterLink :to="talkRoute(r.talk.id)" class="talk">
            <span class="talk-title">{{ r.talk.title }}</span>
            <span class="talk-meta">
              {{ r.talk.speaker }}, {{ r.talk.conference }}
              <span class="faint">
                <template v-if="r.pin_count">{{ r.pin_count }} pinned</template>
                <template v-if="r.pin_count && r.notes_len"> and </template>
                <template v-if="r.notes_len">notes</template>
              </span>
            </span>
          </RouterLink>
        </li>
      </ul>
    </aside>
  </div>
</template>

<style scoped>
.home {
  max-width: 1100px;
  margin: 0 auto;
  padding: 2.5rem 1.25rem 4rem;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 320px;
  gap: 3rem;
}
@media (max-width: 900px) {
  .home {
    grid-template-columns: 1fr;
    gap: 2rem;
  }
}
h1 {
  font-size: var(--fs-5);
  font-weight: 600;
  letter-spacing: -0.01em;
}
.lede {
  max-width: 58ch;
  margin: 0.6rem 0 1.5rem;
  font-size: var(--fs-2);
}
.controls {
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: 0.6rem;
  align-items: center;
  margin-bottom: 1rem;
}
.controls select {
  width: auto;
}
@media (max-width: 600px) {
  .controls {
    grid-template-columns: 1fr;
  }
}
.talks,
.recent ul {
  list-style: none;
  margin: 0;
  padding: 0;
}
.talks li,
.recent li {
  border-top: 1px solid var(--rule);
}
.talks li:last-child,
.recent li:last-child {
  border-bottom: 1px solid var(--rule);
}
.talk {
  display: block;
  padding: 0.7rem 0.25rem;
  color: inherit;
}
.talk:hover {
  text-decoration: none;
  background: var(--paper-2);
}
.talk:hover .talk-title {
  color: var(--blue-2);
}
.talk-title {
  display: block;
}
.talk-meta {
  display: block;
  margin-top: 0.1rem;
}
.badge {
  margin-left: 0.5rem;
  color: var(--gold-2);
}
.recent h2 {
  font-size: var(--fs-3);
  margin-bottom: 0.5rem;
}
.faint.small {
  margin-top: 0.75rem;
}
</style>
