<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { api, type Conference, type TalkSummary } from '../api'
import { talkRoute } from '../router'
import { useLessonStore } from '../stores/lesson'
import { renderMarkdown } from '../utils/markdown'
import landingMd from '../content/landing.md?raw'
import videosJson from '../content/videos.json'

interface Video {
  title: string
  speaker: string
  url: string
}

const lesson = useLessonStore()
const intro = renderMarkdown(landingMd)
const videos = (videosJson as Video[]).filter((v) => v.url)

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

function ytId(url: string): string | null {
  const m = url.match(/(?:v=|youtu\.be\/|shorts\/|embed\/)([A-Za-z0-9_-]{11})/)
  return m ? m[1] : null
}
function thumb(url: string): string | null {
  const id = ytId(url)
  return id ? `https://img.youtube.com/vi/${id}/hqdefault.jpg` : null
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
  <div class="landing">
    <section class="intro serif" v-html="intro"></section>

    <section v-if="videos.length" class="videos">
      <h2>Counsel from Church leaders</h2>
      <ul class="video-row">
        <li v-for="v in videos" :key="v.url">
          <a :href="v.url" target="_blank" rel="noopener" class="video">
            <img v-if="thumb(v.url)" :src="thumb(v.url)!" :alt="`Watch: ${v.title}`" loading="lazy" />
            <span class="v-title">{{ v.title }}</span>
            <span class="v-speaker">{{ v.speaker }}</span>
          </a>
        </li>
      </ul>
    </section>

    <div class="cols">
      <section class="mine">
        <h2>My lessons</h2>
        <p v-if="!lesson.mine.length" class="empty">
          Nothing in progress. Pick a talk below and choose “Add to my lessons” in its header.
        </p>
        <ul v-else class="lesson-list">
          <li v-for="m in lesson.mine" :key="m.talk.id">
            <RouterLink :to="talkRoute(m.talk.id)" class="talk">
              <span class="talk-title">{{ m.talk.title }}</span>
              <span class="talk-meta">
                {{ m.talk.speaker }}, {{ m.talk.conference }}
                <span v-if="lessonMeta(m)" class="faint"> · {{ lessonMeta(m) }}</span>
              </span>
            </RouterLink>
            <button class="quiet small" @click="lesson.removeMine(m.talk.id)">Remove</button>
          </li>
        </ul>

        <template v-if="others.length">
          <h3>Other talks with notes</h3>
          <ul class="lesson-list">
            <li v-for="r in others" :key="r.talk.id">
              <RouterLink :to="talkRoute(r.talk.id)" class="talk">
                <span class="talk-title">{{ r.talk.title }}</span>
                <span class="talk-meta">{{ r.talk.speaker }}, {{ r.talk.conference }}</span>
              </RouterLink>
            </li>
          </ul>
        </template>
      </section>

      <section class="pick">
        <h2>Start a lesson</h2>
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
        <p v-if="currentConf && !results" class="faint small">
          {{ currentConf.label }} <a :href="currentConf.url" target="_blank" rel="noopener">on churchofjesuschrist.org</a>
        </p>
      </section>
    </div>
  </div>
</template>

<style scoped>
.landing {
  max-width: 1100px;
  margin: 0 auto;
  padding: 2.5rem 1.25rem 4rem;
}
.intro {
  max-width: 62ch;
  font-size: 1.1rem;
  line-height: 1.65;
}
.intro :deep(h2) {
  font-size: var(--fs-4);
  margin-bottom: 0.75rem;
}
.intro :deep(p) {
  margin: 0 0 0.9em;
}
.videos {
  margin-top: 2rem;
}
h2 {
  font-size: var(--fs-3);
  margin-bottom: 0.6rem;
}
h3 {
  font-size: var(--fs-2);
  margin: 1.5rem 0 0.4rem;
}
.video-row {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 1rem;
}
.video {
  display: block;
  color: inherit;
}
.video:hover {
  text-decoration: none;
}
.video:hover .v-title {
  color: var(--blue-2);
}
.video img {
  width: 100%;
  aspect-ratio: 16 / 9;
  object-fit: cover;
  border-radius: var(--radius);
  display: block;
  margin-bottom: 0.4rem;
}
.v-title {
  display: block;
  font-family: var(--serif);
  font-weight: 600;
  line-height: 1.3;
}
.v-speaker {
  display: block;
  color: var(--ink-2);
  font-size: var(--fs-0);
}
.cols {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 3rem;
  margin-top: 2.5rem;
  padding-top: 2rem;
  border-top: 1px solid var(--rule);
}
@media (max-width: 900px) {
  .cols {
    grid-template-columns: 1fr;
    gap: 2rem;
  }
}
.lesson-list,
.talks {
  list-style: none;
  margin: 0;
  padding: 0;
}
.lesson-list li,
.talks li {
  border-top: 1px solid var(--rule);
}
.lesson-list li:last-child,
.talks li:last-child {
  border-bottom: 1px solid var(--rule);
}
.lesson-list li {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.lesson-list .talk {
  flex: 1;
  min-width: 0;
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
.talk-title,
.talk-meta {
  display: block;
}
.talk-meta {
  margin-top: 0.1rem;
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
.badge {
  margin-left: 0.5rem;
  color: var(--gold-2);
}
.faint.small {
  margin-top: 0.75rem;
}
</style>
