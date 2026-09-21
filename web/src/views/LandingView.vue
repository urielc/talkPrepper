<script setup lang="ts">
import { RouterLink } from 'vue-router'
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

const lesson = useLessonStore()
if (!lesson.mineLoaded) lesson.loadMine().catch(() => {})

const videos = (videosJson as Video[]).filter((v) => v.url)

/** Split the counsel Markdown on its "## " headings so each section can be placed. */
interface Section {
  title: string
  html: string
}
const sections: Section[] = counselMd
  .split(/^## /m)
  .filter((s) => s.trim())
  .map((block) => {
    const [title, ...rest] = block.split('\n')
    return { title: title.trim(), html: renderMarkdown(rest.join('\n')) }
  })
const columns = sections.filter((s) => s.title !== 'Sources')
const sources = sections.find((s) => s.title === 'Sources')

function ytId(url: string): string | null {
  const m = url.match(/(?:v=|youtu\.be\/|shorts\/|embed\/)([A-Za-z0-9_-]{11})/)
  return m ? m[1] : null
}
function thumb(url: string): string | null {
  const id = ytId(url)
  return id ? `https://img.youtube.com/vi/${id}/hqdefault.jpg` : null
}
</script>

<template>
  <div class="landing">
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

    <nav class="menubar" aria-label="Sections">
      <div class="menubar-inner">
        <RouterLink to="/lessons" class="menu-link">
          Lesson prep
          <span class="menu-sub">{{ lesson.mine.length ? `${lesson.mine.length} in progress · pick or continue a talk` : 'pick a talk to begin' }}</span>
        </RouterLink>
      </div>
    </nav>

    <div class="body">
      <div class="columns">
        <section v-for="s in columns" :key="s.title" class="column">
          <h2>{{ s.title }}</h2>
          <div class="md" v-html="s.html"></div>
        </section>
      </div>

      <section v-if="videos.length" class="videos">
        <h2>Counsel on video</h2>
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

      <section v-if="sources" class="sources">
        <h2>{{ sources.title }}</h2>
        <div class="md" v-html="sources.html"></div>
      </section>
    </div>
  </div>
</template>

<style scoped>
/* ---- hero: fixed navy in both themes, like the Church site's hero band */
.hero {
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
  max-width: 24ch;
}
.hero-text p {
  margin-top: 1rem;
  font-size: var(--fs-2);
  line-height: 1.55;
  max-width: 58ch;
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

/* ---- menu bar */
.menubar {
  background: var(--paper-2);
  border-bottom: 1px solid var(--rule);
}
.menubar-inner {
  max-width: 1400px;
  margin: 0 auto;
  padding: 0 2rem;
  display: flex;
}
.menu-link {
  display: flex;
  align-items: baseline;
  gap: 0.75rem;
  padding: 0.85rem 0;
  font-family: var(--serif);
  font-weight: 600;
  font-size: var(--fs-2);
  color: var(--ink);
  border-bottom: 3px solid var(--gold);
}
.menu-link:hover {
  text-decoration: none;
  color: var(--blue-2);
}
.menu-sub {
  font-family: var(--sans);
  font-weight: 400;
  font-size: var(--fs-0);
  color: var(--ink-2);
}

/* ---- three columns */
.body {
  max-width: 1400px;
  margin: 0 auto;
  padding: 2.5rem 2rem 4rem;
}
.columns {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 3rem;
}
.column h2,
.videos h2,
.sources h2 {
  font-family: var(--serif);
  font-size: var(--fs-3);
  margin-bottom: 0.6rem;
  padding-bottom: 0.4rem;
  border-bottom: 2px solid var(--gold);
}
.md {
  font-size: 1.02rem;
  line-height: 1.55;
  color: var(--ink-2);
}
.md :deep(ul) {
  padding-left: 1.1rem;
  margin: 0;
}
.md :deep(li) {
  margin-bottom: 0.45rem;
}
.md :deep(p) {
  margin: 0 0 0.85rem;
}
.md :deep(a) {
  color: var(--blue-2);
}

/* ---- videos and sources */
.videos,
.sources {
  margin-top: 3rem;
}
.video-row {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 1.25rem;
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
.sources .md {
  font-size: var(--fs-1);
  columns: 2;
  column-gap: 3rem;
}
.sources .md :deep(li) {
  break-inside: avoid;
}

@media (max-width: 1000px) {
  .columns {
    grid-template-columns: 1fr;
    gap: 2rem;
  }
  .sources .md {
    columns: 1;
  }
}
@media (max-width: 760px) {
  .hero-inner {
    grid-template-columns: 1fr;
    padding: 2rem 1.25rem;
  }
  .menubar-inner,
  .body {
    padding-left: 1.25rem;
    padding-right: 1.25rem;
  }
}
</style>
