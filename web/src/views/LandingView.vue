<script setup lang="ts">
import { ref } from 'vue'
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
  blurb?: string
}

const lesson = useLessonStore()
if (!lesson.mineLoaded) lesson.loadMine().catch(() => {})

const videos = (videosJson as Video[]).filter((v) => v.url)
/** The first video is featured with an in-page player; any others form a row of thumbnails. */
const featured = videos[0]
const more = videos.slice(1)
const playing = ref(false)

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
function thumb(url: string, size: 'hqdefault' | 'maxresdefault' = 'hqdefault'): string | null {
  const id = ytId(url)
  return id ? `https://img.youtube.com/vi/${id}/${size}.jpg` : null
}
/** Privacy-enhanced embed; nothing loads from YouTube until the poster is clicked. */
function embed(url: string): string | null {
  const id = ytId(url)
  return id ? `https://www.youtube-nocookie.com/embed/${id}?autoplay=1&rel=0` : null
}
/** maxresdefault is missing for some uploads; fall back to the always-present hqdefault. */
function posterFallback(e: Event) {
  const img = e.target as HTMLImageElement
  if (featured && !img.src.endsWith('hqdefault.jpg')) img.src = thumb(featured.url)!
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

      <section v-if="featured" class="videos">
        <h2>Counsel on video</h2>

        <div class="feature">
          <div class="player">
            <iframe
              v-if="playing && embed(featured.url)"
              :src="embed(featured.url)!"
              :title="featured.title"
              allow="autoplay; encrypted-media; picture-in-picture; fullscreen"
              referrerpolicy="strict-origin-when-cross-origin"
              allowfullscreen
            ></iframe>
            <button v-else type="button" class="poster" :aria-label="`Play: ${featured.title}`" @click="playing = true">
              <img v-if="thumb(featured.url)" :src="thumb(featured.url, 'maxresdefault')!" alt="" @error="posterFallback" />
              <span class="play" aria-hidden="true">
                <svg viewBox="0 0 24 24" width="28" height="28"><path d="M8 5v14l11-7z" fill="currentColor" /></svg>
              </span>
            </button>
          </div>
          <div class="feature-text">
            <h3 class="serif">{{ featured.title }}</h3>
            <p class="f-speaker">{{ featured.speaker }}</p>
            <p v-if="featured.blurb" class="f-blurb">{{ featured.blurb }}</p>
            <a :href="featured.url" target="_blank" rel="noopener" class="f-link">Watch on YouTube</a>
          </div>
        </div>

        <ul v-if="more.length" class="video-row">
          <li v-for="v in more" :key="v.url">
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
.feature {
  display: grid;
  grid-template-columns: minmax(0, 7fr) minmax(0, 5fr);
  gap: 2.5rem;
  align-items: center;
  margin-top: 1.25rem;
}
.player {
  position: relative;
  aspect-ratio: 16 / 9;
  background: #000;
  border-radius: var(--radius);
  overflow: hidden;
}
.player iframe {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  border: 0;
}
.poster {
  position: absolute;
  inset: 0;
  width: 100%;
  padding: 0;
  border: 0;
  background: none;
  cursor: pointer;
  color: #fff;
}
.poster img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.play {
  position: absolute;
  left: 50%;
  top: 50%;
  width: 4.25rem;
  height: 4.25rem;
  margin: -2.125rem 0 0 -2.125rem;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: rgba(11, 46, 89, 0.82);
  border: 2px solid rgba(255, 255, 255, 0.85);
  transition: background 120ms ease;
}
.play svg {
  margin-left: 3px;
}
.poster:hover .play,
.poster:focus-visible .play {
  background: var(--gold);
}
.poster:focus-visible {
  outline: none;
  box-shadow: inset var(--focus);
}
.feature-text h3 {
  font-size: var(--fs-4);
  line-height: 1.2;
  font-weight: 600;
  max-width: 22ch;
}
.f-speaker {
  margin-top: 0.4rem;
  color: var(--ink-2);
  font-size: var(--fs-2);
}
.f-blurb {
  margin-top: 1rem;
  line-height: 1.55;
  color: var(--ink-2);
  max-width: 48ch;
}
.f-link {
  display: inline-block;
  margin-top: 1.1rem;
  color: var(--blue-2);
  font-size: var(--fs-1);
  border-bottom: 1px solid currentColor;
}
.f-link:hover {
  text-decoration: none;
  color: var(--gold-2);
}
.video-row {
  list-style: none;
  margin: 2rem 0 0;
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
  .feature {
    grid-template-columns: 1fr;
    gap: 1.25rem;
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
