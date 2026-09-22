<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { api, type Conference, type TalkSummary } from '../api'
import { talkRoute } from '../router'
import { useAuthStore } from '../stores/auth'
import { useLessonStore } from '../stores/lesson'

const auth = useAuthStore()
const lesson = useLessonStore()

const conferences = ref<Conference[]>([])
const conferenceId = ref('')
const talks = ref<TalkSummary[]>([])
const q = ref('')
const allConferences = ref(false)
const results = ref<TalkSummary[] | null>(null)
const others = ref<{ talk: TalkSummary; notes_len: number; pin_count: number }[]>([])
const loading = ref(false)
const error = ref<string | null>(null)

onMounted(async () => {
  try {
    if (!lesson.mineLoaded) await lesson.loadMine()
    conferences.value = await api.conferences()
    if (conferences.value.length) conferenceId.value = conferences.value[0].id
    const recent = await api.lessons()
    others.value = recent.filter((r) => !lesson.isMine(r.talk.id))
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
const currentConf = computed(() => conferences.value.find((c) => c.id === conferenceId.value))
const firstName = computed(() => (auth.user?.name || '').split(' ')[0])

/** Clears a talk from "Other talks with notes"; the talk and anything left on it stay. */
async function hideOther(talkId: string) {
  try {
    await api.hideLesson(talkId)
    others.value = others.value.filter((r) => r.talk.id !== talkId)
  } catch (e: any) {
    error.value = e.message
  }
}

function lessonMeta(m: { notes_len: number; pin_count: number; has_digest: boolean }): string {
  const parts: string[] = []
  if (m.notes_len) parts.push('notes')
  if (m.pin_count) parts.push(`${m.pin_count} pinned`)
  if (m.has_digest) parts.push('digest')
  return parts.join(', ')
}
</script>

<template>
  <div class="lessons">
    <section class="col mine">
      <h1>{{ firstName ? `${firstName}, your lessons` : 'Your lessons' }}</h1>
      <p v-if="!lesson.mine.length" class="empty">
        Nothing in progress. Pick a talk on the right and choose “Add to my lessons” in its header.
      </p>
      <ul v-else class="cards">
        <li v-for="m in lesson.mine" :key="m.talk.id" class="card">
          <RouterLink :to="talkRoute(m.talk.id)" class="card-main">
            <span class="card-title">{{ m.talk.title }}</span>
            <span class="talk-meta">{{ m.talk.speaker }}, {{ m.talk.conference }}</span>
            <span v-if="lessonMeta(m)" class="card-meta">{{ lessonMeta(m) }}</span>
          </RouterLink>
          <div class="card-actions">
            <RouterLink :to="talkRoute(m.talk.id)" class="btn-link">Continue</RouterLink>
            <button class="quiet small" @click="lesson.removeMine(m.talk.id)">Remove</button>
          </div>
        </li>
      </ul>

      <template v-if="others.length">
        <h3>Other talks with notes</h3>
        <ul class="plain">
          <li v-for="r in others" :key="r.talk.id" class="other">
            <RouterLink :to="talkRoute(r.talk.id)" class="talk">
              <span class="talk-title">{{ r.talk.title }}</span>
              <span class="talk-meta">{{ r.talk.speaker }}, {{ r.talk.conference }}</span>
            </RouterLink>
            <button
              class="quiet small"
              title="Clear from this list. The talk is not deleted, and new notes or pins bring it back."
              :aria-label="`Delete ${r.talk.title} from this list`"
              @click="hideOther(r.talk.id)"
            >
              Delete
            </button>
          </li>
        </ul>
      </template>
    </section>

    <aside class="col pick">
      <h2>Start a lesson</h2>
      <div class="controls">
        <select v-model="conferenceId" aria-label="Conference">
          <option v-for="c in conferences" :key="c.id" :value="c.id">{{ c.label }}</option>
        </select>
        <input v-model="q" type="search" placeholder="Speaker or title" aria-label="Find a talk" />
        <label class="row small muted"><input v-model="allConferences" type="checkbox" /> Search all conferences</label>
      </div>
      <div v-if="error" class="notice error">{{ error }}</div>
      <div v-else-if="loading && !shown.length" class="muted">Loading…</div>
      <p v-else-if="!shown.length" class="empty">No talks match. Try another spelling, or search all conferences.</p>
      <ol v-else class="plain talks">
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
      <p v-if="currentConf && !results" class="faint small">
        {{ currentConf.label }} <a :href="currentConf.url" target="_blank" rel="noopener">on churchofjesuschrist.org</a>
      </p>
    </aside>
  </div>
</template>

<style scoped>
.lessons {
  max-width: 1400px;
  margin: 0 auto;
  padding: 2rem 2rem 4rem;
  display: grid;
  grid-template-columns: minmax(0, 5fr) minmax(300px, 4fr);
  gap: 3rem;
  align-items: start;
}
h1 {
  font-size: var(--fs-4);
  margin-bottom: 0.9rem;
}
h2 {
  font-size: var(--fs-3);
  margin-bottom: 0.75rem;
}
h3 {
  font-size: var(--fs-2);
  margin: 1.75rem 0 0.4rem;
}
.cards {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 0.9rem;
}
.card {
  border: 1px solid var(--rule);
  border-radius: 6px;
  padding: 1rem 1.1rem;
  display: flex;
  gap: 1rem;
  align-items: center;
  background: var(--paper);
}
.card-main {
  flex: 1;
  min-width: 0;
  color: inherit;
  display: block;
}
.card-main:hover {
  text-decoration: none;
}
.card-main:hover .card-title {
  color: var(--blue-2);
}
.card-title {
  display: block;
  font-family: var(--serif);
  font-size: var(--fs-3);
  font-weight: 600;
  line-height: 1.25;
}
.card-meta {
  display: block;
  color: var(--gold-2);
  font-size: var(--fs-0);
  margin-top: 0.25rem;
}
.card-actions {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 0.35rem;
  flex-shrink: 0;
}
.btn-link {
  display: inline-block;
  padding: 0.4rem 0.9rem;
  border-radius: var(--radius);
  background: var(--blue);
  color: #fff;
  font-weight: 600;
}
.btn-link:hover {
  text-decoration: none;
  filter: brightness(1.1);
}
.pick {
  border: 1px solid var(--rule);
  border-radius: 6px;
  padding: 1.1rem 1.1rem 0.75rem;
  background: var(--paper-2);
}
.controls {
  display: grid;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
}
.pick .talks {
  max-height: 65vh;
  overflow: auto;
  background: var(--paper);
  border: 1px solid var(--rule);
  border-radius: var(--radius);
}
.plain {
  list-style: none;
  margin: 0;
  padding: 0;
}
.plain li + li {
  border-top: 1px solid var(--rule);
}
.other {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.other .talk {
  flex: 1;
  min-width: 0;
}
.other button {
  flex-shrink: 0;
}
.talk {
  display: block;
  padding: 0.55rem 0.7rem;
  color: inherit;
}
.talk:hover {
  text-decoration: none;
  background: var(--paper-2);
}
.talk:hover .talk-title {
  color: var(--blue-2);
}
.talk-title,
.talk-meta {
  display: block;
}
.talk-meta {
  margin-top: 0.1rem;
}
.badge {
  margin-left: 0.5rem;
  color: var(--gold-2);
}
.faint.small {
  margin-top: 0.6rem;
}
@media (max-width: 860px) {
  .lessons {
    grid-template-columns: 1fr;
    padding: 1.5rem 1.25rem 3rem;
    gap: 2rem;
  }
}
</style>
