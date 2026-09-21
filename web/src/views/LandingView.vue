<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { api, type Conference, type TalkSummary } from '../api'
import { talkRoute } from '../router'
import { useAuthStore } from '../stores/auth'
import { useLessonStore } from '../stores/lesson'
import { renderMarkdown } from '../utils/markdown'
import counselMd from '../content/landing.md?raw'
import hero from '../content/hero.json'
import videosJson from '../content/videos.json'

interface Video {
  title: string
  speaker: string
  url: string
}

const auth = useAuthStore()
const lesson = useLessonStore()
const counsel = renderMarkdown(counselMd)
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
const firstName = computed(() => (auth.user?.name || '').split(' ')[0])

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
    <!-- Hero band: statement on the left, the Handbook's line on the right -->
    <section class="hero">
      <div class="hero-inner">
        <div class="hero-text">
          <h1>{{ hero.title }}</h1>
          <p>{{ hero.subtitle }}</p>
        </div>
        <aside class="handbook">
          <div class="hb-label">{{ hero.handbook.label }}</div>
          <p class="serif">{{ hero.handbook.text }}</p>
          <a :href="hero.handbook.link" target="_blank" rel="noopener" class="hb-link">{{ hero.handbook.linkLabel }}</a>
        </aside>
      </div>
    </section>

    <div class="body">
      <!-- Left: counsel and videos -->
      <aside class="col counsel">
        <div class="md" v-html="counsel"></div>
        <section v-if="videos.length" class="videos">
          <h2>Counsel on video</h2>
          <ul class="video-list">
            <li v-for="v in videos" :key="v.url">
              <a :href="v.url" target="_blank" rel="noopener" class="video">
                <img v-if="thumb(v.url)" :src="thumb(v.url)!" :alt="`Watch: ${v.title}`" loading="lazy" />
                <span class="v-title">{{ v.title }}</span>
                <span class="v-speaker">{{ v.speaker }}</span>
              </a>
            </li>
          </ul>
        </section>
      </aside>

      <!-- Centre: the teacher's lessons -->
      <section class="col mine">
        <h2>{{ firstName ? `${firstName}, your lessons` : 'My lessons' }}</h2>
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
            <li v-for="r in others" :key="r.talk.id">
              <RouterLink :to="talkRoute(r.talk.id)" class="talk">
                <span class="talk-title">{{ r.talk.title }}</span>
                <span class="talk-meta">{{ r.talk.speaker }}, {{ r.talk.conference }}</span>
              </RouterLink>
            </li>
          </ul>
        </template>
      </section>

      <!-- Right: start a lesson -->
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
  </div>
</template>

<style scoped>
/* ---- hero */
.hero {
  /* fixed navy in both themes, like the Church site's hero band */
  background: #0b2e59;
  color: #fff;
}
.hero-inner {
  max-width: 1400px;
  margin: 0 auto;
  padding: 2.75rem 2rem;
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr);
  gap: 2.5rem;
  align-items: center;
}
.hero-text h1 {
  color: #fff;
  font-size: clamp(1.7rem, 2.6vw, 2.4rem);
  line-height: 1.15;
  letter-spacing: -0.01em;
  max-width: 22ch;
}
.hero-text p {
  margin-top: 1rem;
  font-size: var(--fs-2);
  line-height: 1.55;
  max-width: 52ch;
  color: rgba(255, 255, 255, 0.88);
}
.handbook {
  background: rgba(255, 255, 255, 0.08);
  border-left: 3px solid #c9a227;
  padding: 1.1rem 1.3rem;
  border-radius: 0 var(--radius) var(--radius) 0;
}
.hb-label {
  font-size: var(--fs-0);
  color: #e6d9a8;
  margin-bottom: 0.4rem;
}
.handbook p {
  line-height: 1.55;
  font-size: 1.02rem;
}
.hb-link {
  display: inline-block;
  margin-top: 0.75rem;
  color: #fff;
  border: 1px solid rgba(255, 255, 255, 0.6);
  border-radius: var(--radius);
  padding: 0.35rem 0.75rem;
  font-size: var(--fs-0);
}
.hb-link:hover {
  background: rgba(255, 255, 255, 0.12);
  text-decoration: none;
}

/* ---- three columns */
.body {
  max-width: 1400px;
  margin: 0 auto;
  padding: 2rem 2rem 4rem;
  display: grid;
  grid-template-columns: minmax(260px, 3fr) minmax(0, 5fr) minmax(280px, 4fr);
  gap: 2.5rem;
  align-items: start;
}
.col h2 {
  font-size: var(--fs-3);
  margin-bottom: 0.75rem;
}
h3 {
  font-size: var(--fs-2);
  margin: 1.75rem 0 0.4rem;
}

/* counsel column */
.counsel .md {
  font-size: var(--fs-1);
  line-height: 1.5;
  color: var(--ink-2);
}
.counsel .md :deep(h2) {
  font-family: var(--serif);
  font-size: var(--fs-2);
  color: var(--ink);
  margin: 0 0 0.4rem;
  padding-top: 1rem;
  border-top: 1px solid var(--rule);
}
.counsel .md :deep(h2:first-child) {
  padding-top: 0;
  border-top: 0;
}
.counsel .md :deep(ul) {
  padding-left: 1.1rem;
  margin: 0 0 1rem;
}
.counsel .md :deep(li) {
  margin-bottom: 0.3rem;
}
.counsel .md :deep(p) {
  margin: 0 0 0.75rem;
}
.videos {
  margin-top: 1.25rem;
  padding-top: 1rem;
  border-top: 1px solid var(--rule);
}
.video-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 0.9rem;
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
  margin-bottom: 0.35rem;
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

/* centre: lesson cards */
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

/* right: picker */
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
  max-height: 60vh;
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

@media (max-width: 1100px) {
  .body {
    grid-template-columns: minmax(0, 1fr) minmax(280px, 1fr);
  }
  .counsel {
    grid-column: 1 / -1;
    order: 3;
    column-count: 2;
    column-gap: 2.5rem;
  }
}
@media (max-width: 760px) {
  .hero-inner {
    grid-template-columns: 1fr;
    padding: 2rem 1.25rem;
  }
  .body {
    grid-template-columns: 1fr;
    padding: 1.5rem 1.25rem 3rem;
    gap: 2rem;
  }
  .counsel {
    column-count: 1;
  }
}
</style>
