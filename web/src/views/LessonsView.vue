<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { api, AUDIENCE_LABELS, type Conference, type MyLesson, type StudyListItem, type TalkSummary } from '../api'
import AudienceSelect from '../components/AudienceSelect.vue'
import { lessonRoute, talkRoute } from '../router'
import { useAuthStore } from '../stores/auth'
import { useLessonStore } from '../stores/lesson'
import { useTopicStore } from '../stores/topic'

const auth = useAuthStore()
const lesson = useLessonStore()
const route = useRoute()
const router = useRouter()
const topicStore = useTopicStore()

// How to start: by topic (opens the topic page) or by conference. Old ?topic= links go to the topic page.
type Finder = 'topic' | 'conference'
const initialTopic = typeof route.query.topic === 'string' ? route.query.topic : ''
if (initialTopic) router.replace({ path: '/topic', query: { topic: initialTopic } })
const wantTopic = route.query.find === 'topic'
const topicQuery = ref('')

function openTopic() {
  const t = topicQuery.value.trim()
  if (t.length >= 2) router.push({ path: '/topic', query: { topic: t } })
}
const finder = ref<Finder>(wantTopic ? 'topic' : 'conference')
if (!wantTopic) {
  try {
    const saved = localStorage.getItem('lp.finder')
    if (saved === 'topic' || saved === 'conference') finder.value = saved
  } catch {
    /* storage unavailable */
  }
}
watch(finder, (f) => {
  try {
    localStorage.setItem('lp.finder', f)
  } catch {
    /* ignore */
  }
})

const conferences = ref<Conference[]>([])
const conferenceId = ref('')
const talks = ref<TalkSummary[]>([])
const q = ref('')
const allConferences = ref(false)
const results = ref<TalkSummary[] | null>(null)
const others = ref<{ talk: TalkSummary; notes_len: number; pin_count: number }[]>([])
const otherStudies = ref<StudyListItem[]>([])
const loading = ref(false)
const error = ref<string | null>(null)

onMounted(async () => {
  try {
    if (!lesson.mineLoaded) await lesson.loadMine()
    conferences.value = await api.conferences()
    if (conferences.value.length) conferenceId.value = conferences.value[0].id
    const recent = await api.lessons()
    others.value = recent.filter((r) => !lesson.isMine(r.talk.id))
    await loadOtherStudies()
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

async function loadOtherStudies() {
  otherStudies.value = (await api.studies()).filter((s) => !s.in_my_lessons)
}

/** Takes a lesson off the list. A study is kept and moves to "Your studies" below. */
async function removeLesson(m: MyLesson) {
  try {
    await lesson.removeMine(m.lesson_id)
    if (m.kind === 'study') await loadOtherStudies()
  } catch (e: any) {
    error.value = e.message
  }
}

async function addStudy(s: StudyListItem) {
  try {
    await lesson.addMine(s.key)
    otherStudies.value = otherStudies.value.filter((o) => o.id !== s.id)
  } catch (e: any) {
    error.value = e.message
  }
}

async function deleteStudy(s: StudyListItem) {
  if (!window.confirm(`Delete the study “${s.topic}” with its notes and pins? This cannot be undone.`)) return
  try {
    await api.deleteStudy(s.id)
    otherStudies.value = otherStudies.value.filter((o) => o.id !== s.id)
  } catch (e: any) {
    error.value = e.message
  }
}

function lessonMeta(m: MyLesson): string {
  const parts: string[] = []
  if (m.notes_len) parts.push('notes')
  if (m.pin_count) parts.push(`${m.pin_count} pinned`)
  if (m.has_digest) parts.push(m.kind === 'study' ? 'summary' : 'digest')
  return parts.join(', ')
}
</script>

<template>
  <div class="lessons">
    <section class="col mine">
      <h1>{{ firstName ? `${firstName}, your lessons` : 'Your lessons' }}</h1>
      <p v-if="!lesson.mine.length" class="empty">
        Nothing in progress. Search a topic to build a study, find a talk by conference, or open a talk
        and choose “Add to my lessons” in its header.
      </p>
      <ul v-else class="cards">
        <li v-for="m in lesson.mine" :key="m.lesson_id" class="card">
          <RouterLink :to="lessonRoute(m)" class="card-main">
            <span class="card-title">{{ m.talk ? m.talk.title : m.study?.topic }}</span>
            <span v-if="m.talk" class="talk-meta">{{ m.talk.speaker }}, {{ m.talk.conference }}</span>
            <span v-else class="talk-meta">Topic study, {{ m.study?.source_count }} {{ m.study?.source_count === 1 ? 'source' : 'sources' }}</span>
            <span class="card-meta">
              {{ AUDIENCE_LABELS[m.audience] || 'Elders quorum' }}<template v-if="lessonMeta(m)"> · {{ lessonMeta(m) }}</template>
            </span>
          </RouterLink>
          <div class="card-actions">
            <RouterLink :to="lessonRoute(m)" class="btn-link">Continue</RouterLink>
            <button
              class="quiet small"
              :title="m.kind === 'study' ? 'Remove from my lessons. The study stays under Your studies.' : 'Remove from my lessons'"
              @click="removeLesson(m)"
            >
              Remove
            </button>
          </div>
        </li>
      </ul>

      <template v-if="otherStudies.length">
        <h3>Your studies</h3>
        <ul class="plain">
          <li v-for="s in otherStudies" :key="s.id" class="other">
            <RouterLink :to="`/study/${s.id}`" class="talk">
              <span class="talk-title">{{ s.topic }}</span>
              <span class="talk-meta">
                Topic study, {{ s.source_count }} {{ s.source_count === 1 ? 'source' : 'sources' }} · {{ s.audience_label }}
              </span>
            </RouterLink>
            <RouterLink :to="`/study/${s.id}`" class="small open">Open</RouterLink>
            <button class="quiet small" @click="addStudy(s)">Add to my lessons</button>
            <button class="quiet small" title="Deletes the study with its notes and pins" @click="deleteStudy(s)">Delete</button>
          </li>
        </ul>
      </template>

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
      <div class="seg finder" role="tablist" aria-label="Find a talk">
        <button type="button" role="tab" class="small" :aria-selected="finder === 'topic'" :class="{ on: finder === 'topic' }" @click="finder = 'topic'">
          By topic
        </button>
        <button type="button" role="tab" class="small" :aria-selected="finder === 'conference'" :class="{ on: finder === 'conference' }" @click="finder = 'conference'">
          By conference
        </button>
      </div>
      <template v-if="finder === 'topic'">
        <form class="topic-start" @submit.prevent="openTopic">
          <AudienceSelect :model-value="topicStore.audience" title="Who the lesson is for" @change="topicStore.setAudience" />
          <div class="row">
            <input
              v-model="topicQuery"
              type="search"
              class="grow"
              placeholder="A topic, e.g. forgiveness, ministering, the Sabbath"
              aria-label="Topic"
              maxlength="300"
            />
            <button type="submit" class="primary" :disabled="topicQuery.trim().length < 2">Search</button>
          </div>
        </form>
        <p class="faint small">
          Search talks, manuals, songs, scriptures, Josephus and the Apocrypha on a topic, then queue sources for an AI
          study summary.
        </p>
        <p v-if="topicStore.queue.length" class="small">
          <RouterLink to="/topic">{{ topicStore.queue.length }} {{ topicStore.queue.length === 1 ? 'source' : 'sources' }} queued. Continue</RouterLink>
        </p>
      </template>
      <template v-else>
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
      </template>
    </aside>
  </div>
</template>

<style scoped>
.topic-start {
  display: grid;
  gap: 0.5rem;
  margin: 0.5rem 0 0.4rem;
}

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
.finder {
  margin-bottom: 0.75rem;
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
.other button,
.other .open {
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
