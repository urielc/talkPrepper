<script setup lang="ts">
import { ref, watch } from 'vue'
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

/**
 * The counsel accordion. Only one panel is open at a time, so the state is the open
 * panel's key rather than a flag per section; clicking the open one closes it.
 */
const HANDBOOK_KEY = 'handbook'
const OPEN_STORE = 'lp.landing.open'
const openKey = ref(columns[0]?.title ?? '')
try {
  const saved = localStorage.getItem(OPEN_STORE)
  if (saved !== null) openKey.value = saved
} catch {
  /* storage unavailable */
}
watch(openKey, (v) => {
  try {
    localStorage.setItem(OPEN_STORE, v)
  } catch {
    /* ignore */
  }
})
function toggle(key: string) {
  openKey.value = openKey.value === key ? '' : key
}

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
        <h1 class="quote">&ldquo;{{ hero.quote }}&rdquo;</h1>
        <p class="attrib">&mdash; {{ hero.attribution }}</p>
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
      <!-- The video carries the page's message, so it and the counsel share the first screen. -->
      <div class="stage">
        <section v-if="featured" class="stage-video">
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
          <div class="caption">
            <h2 class="serif">{{ featured.title }}</h2>
            <p class="c-meta">
              {{ featured.speaker }}<span class="sep" aria-hidden="true"> · </span><a
                :href="featured.url"
                target="_blank"
                rel="noopener"
                >Watch on YouTube</a
              >
            </p>
            <p v-if="featured.blurb" class="c-blurb">{{ featured.blurb }}</p>
          </div>
        </section>

        <div class="counsel">
          <section v-for="(s, i) in columns" :key="s.title" class="item" :class="{ open: openKey === s.title }">
            <button
              type="button"
              class="section-head"
              :aria-expanded="openKey === s.title"
              :aria-controls="`counsel-panel-${i}`"
              @click="toggle(s.title)"
            >
              <span class="title">{{ s.title }}</span>
              <span class="chev" aria-hidden="true">▾</span>
            </button>
            <div v-show="openKey === s.title" :id="`counsel-panel-${i}`" class="panel">
              <div class="md" v-html="s.html"></div>
            </div>
          </section>

          <section class="item" :class="{ open: openKey === HANDBOOK_KEY }">
            <button
              type="button"
              class="section-head"
              :aria-expanded="openKey === HANDBOOK_KEY"
              aria-controls="counsel-panel-handbook"
              @click="toggle(HANDBOOK_KEY)"
            >
              <span class="title">{{ hero.handbook.shortLabel }}</span>
              <span class="chev" aria-hidden="true">▾</span>
            </button>
            <div v-show="openKey === HANDBOOK_KEY" id="counsel-panel-handbook" class="panel">
              <p class="hb-label">{{ hero.handbook.label }}</p>
              <p class="serif hb-text">{{ hero.handbook.text }}</p>
              <a :href="hero.handbook.link" target="_blank" rel="noopener" class="hb-link">{{ hero.handbook.linkLabel }}</a>
            </div>
          </section>
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

      <section v-if="sources" class="sources">
        <h2>{{ sources.title }}</h2>
        <div class="md" v-html="sources.html"></div>
      </section>
    </div>
  </div>
</template>

<style scoped>
/* ---- hero: a headline strip, fixed navy in both themes, like the Church site's hero band */
.hero {
  background: #0b2e59;
  color: #fff;
}
.hero-inner {
  max-width: 1400px;
  margin: 0 auto;
  padding: 1.5rem 2rem;
}
.quote {
  color: #fff;
  font-size: clamp(1.2rem, 1.75vw, 1.6rem);
  line-height: 1.3;
  letter-spacing: -0.01em;
  max-width: 62ch;
  text-wrap: balance;
}
.attrib {
  margin-top: 0.6rem;
  font-size: var(--fs-1);
  color: #e6d9a8;
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

/* ---- the first screen: player beside the collapsible counsel */
.body {
  max-width: 1400px;
  margin: 0 auto;
  padding: 1.75rem 2rem 4rem;
}
.stage {
  /* What is left of the viewport under the topbar, hero strip, menu bar and the caption. */
  --stage-h: clamp(200px, calc(100vh - 27rem), 460px);
  --stage-h: clamp(200px, calc(100svh - 27rem), 460px);
  display: grid;
  grid-template-columns: minmax(0, 7fr) minmax(0, 5fr);
  gap: 2rem;
  align-items: start;
}
.player {
  /* Clamp the width, not the height, so the box never stops being 16:9. */
  width: min(100%, calc(var(--stage-h) * 16 / 9));
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
.caption {
  width: min(100%, calc(var(--stage-h) * 16 / 9));
  margin-top: 0.85rem;
}
.caption h2 {
  font-size: var(--fs-2);
  line-height: 1.25;
  font-weight: 600;
  border: 0;
  padding: 0;
  margin: 0;
}
.c-meta {
  margin-top: 0.2rem;
  color: var(--ink-2);
  font-size: var(--fs-1);
}
.c-meta a {
  color: var(--blue-2);
}
.c-blurb {
  margin-top: 0.45rem;
  color: var(--ink-2);
  font-size: var(--fs-1);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* ---- collapsible counsel column */
.counsel {
  max-height: calc(var(--stage-h) + 5rem);
  /* Explicitly hidden: `overflow-y: auto` alone makes the x axis `auto` too, which
     showed a scrollbar for the pixel the vertical one takes off the content width. */
  overflow: hidden auto;
}
.item {
  margin-bottom: 1rem;
  /* The bar marks the open panel, the way the menu's underline marks the active
     link. Held transparent when closed so opening one shifts nothing sideways. */
  border-left: 3px solid transparent;
  padding-left: 0.75rem;
}
.item.open {
  border-left-color: var(--gold);
}
.item:last-child {
  margin-bottom: 0;
}
.panel {
  padding-top: 0.5rem;
}
.hb-label {
  color: var(--ink-2);
  font-size: var(--fs-0);
  margin-bottom: 0.4rem;
}
.hb-text {
  line-height: 1.55;
  color: var(--ink);
}
.hb-link {
  display: inline-block;
  margin-top: 0.7rem;
  color: var(--blue-2);
  border: 1px solid var(--rule-strong);
  border-radius: var(--radius);
  padding: 0.3rem 0.7rem;
  font-size: var(--fs-0);
}
.hb-link:hover {
  background: var(--paper-2);
  text-decoration: none;
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
.md :deep(p:last-child) {
  margin-bottom: 0;
}
/* The lists carry no bottom margin, so a paragraph following one sets its own gap. */
.md :deep(ul + p) {
  margin-top: 0.85rem;
}
.md :deep(a) {
  color: var(--blue-2);
}

/* ---- below the fold: any further videos, then sources */
.sources {
  margin-top: 3rem;
}
.sources h2 {
  font-family: var(--serif);
  font-size: var(--fs-3);
  margin-bottom: 0.6rem;
  padding-bottom: 0.4rem;
  border-bottom: 2px solid var(--gold);
}
.video-row {
  list-style: none;
  margin: 2.5rem 0 0;
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
  .stage {
    grid-template-columns: 1fr;
    gap: 1.75rem;
  }
  .player,
  .caption {
    width: 100%;
  }
  .counsel {
    max-height: none;
    overflow-y: visible;
  }
  .sources .md {
    columns: 1;
  }
}
@media (max-width: 760px) {
  .hero-inner {
    padding: 1.5rem 1.25rem;
  }
  .menubar-inner,
  .body {
    padding-left: 1.25rem;
    padding-right: 1.25rem;
  }
}
</style>
