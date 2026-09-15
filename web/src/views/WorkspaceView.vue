<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { api, type TalkDetail } from '../api'
import { talkRoute } from '../router'
import { useLessonStore } from '../stores/lesson'
import ChatTab from '../components/ChatTab.vue'
import NotesTab from '../components/NotesTab.vue'
import RelatedTab from '../components/RelatedTab.vue'
import ScripturesTab from '../components/ScripturesTab.vue'
import SearchTab from '../components/SearchTab.vue'
import TalkReader from '../components/TalkReader.vue'

const props = defineProps<{ talkId: string }>()
const route = useRoute()
const router = useRouter()
const lesson = useLessonStore()

const talk = ref<TalkDetail | null>(null)
const error = ref<string | null>(null)
const draft = ref('')

type Tab = 'related' | 'scriptures' | 'search' | 'ask' | 'notes'
const tabs: { id: Tab; label: string }[] = [
  { id: 'related', label: 'Related talks' },
  { id: 'scriptures', label: 'Scriptures' },
  { id: 'search', label: 'Search' },
  { id: 'ask', label: 'Ask AI' },
  { id: 'notes', label: 'Notes & pins' },
]
const tab = computed<Tab>(() => (tabs.some((t) => t.id === route.query.tab) ? (route.query.tab as Tab) : 'related'))
function setTab(t: Tab) {
  router.replace({ query: { ...route.query, tab: t } })
}

watch(
  () => props.talkId,
  async (id) => {
    talk.value = null
    error.value = null
    try {
      const [t] = await Promise.all([api.talk(id), lesson.load(id)])
      talk.value = t
      document.title = `${t.title} · Lesson Prep`
    } catch (e: any) {
      error.value = e.message
    }
  },
  { immediate: true },
)

function ask(text: string) {
  draft.value = `About this passage from the talk:\n\n“${text}”\n\n`
  setTab('ask')
}
</script>

<template>
  <div v-if="error" class="notice error" style="margin: 1.5rem">{{ error }} <RouterLink to="/">Choose another talk</RouterLink></div>
  <div v-else-if="!talk" class="muted" style="margin: 1.5rem">Loading talk…</div>
  <div v-else class="workspace">
    <section class="reader-col">
      <header class="talk-head">
        <nav class="crumbs small">
          <RouterLink to="/">Talks</RouterLink> / <span class="muted">{{ talk.conference }}</span>
        </nav>
        <h1>{{ talk.title }}</h1>
        <div class="byline">
          <span>{{ talk.speaker }}</span>
          <span class="muted">{{ talk.conference }}</span>
          <a :href="talk.url" target="_blank" rel="noopener">Read on churchofjesuschrist.org</a>
        </div>
        <div class="row between neighbors small">
          <RouterLink v-if="talk.prev" :to="talkRoute(talk.prev.id)" class="muted">‹ {{ talk.prev.title }}</RouterLink>
          <span v-else></span>
          <RouterLink v-if="talk.next" :to="talkRoute(talk.next.id)" class="muted">{{ talk.next.title }} ›</RouterLink>
        </div>
      </header>
      <TalkReader :talk="talk" @ask="ask" />
    </section>

    <aside class="tools">
      <div class="tabs" role="tablist">
        <button
          v-for="t in tabs"
          :key="t.id"
          role="tab"
          :aria-selected="tab === t.id"
          class="tab"
          :class="{ on: tab === t.id }"
          @click="setTab(t.id)"
        >
          {{ t.label }}
          <span v-if="t.id === 'notes' && lesson.pins.length" class="count">{{ lesson.pins.length }}</span>
          <span v-else-if="t.id === 'scriptures' && talk.scriptures.length" class="count">{{ talk.scriptures.length }}</span>
        </button>
      </div>
      <div class="tabpanel" role="tabpanel">
        <KeepAlive>
          <RelatedTab v-if="tab === 'related'" :talk-id="talk.id" />
          <ScripturesTab v-else-if="tab === 'scriptures'" :talk="talk" />
          <SearchTab v-else-if="tab === 'search'" />
          <ChatTab v-else-if="tab === 'ask'" :talk-id="talk.id" :draft="draft" />
          <NotesTab v-else :talk-id="talk.id" />
        </KeepAlive>
      </div>
    </aside>
  </div>
</template>

<style scoped>
.workspace {
  display: grid;
  grid-template-columns: minmax(0, 1fr) var(--panel-width);
  height: calc(100vh - var(--header-h));
}
.reader-col {
  overflow: auto;
  padding: 1.75rem 3rem 5rem;
}
.talk-head {
  max-width: var(--reader-width);
  margin-bottom: 1.75rem;
}
.crumbs {
  margin-bottom: 0.75rem;
  color: var(--ink-2);
}
h1 {
  font-size: var(--fs-5);
  font-weight: 600;
  letter-spacing: -0.01em;
  line-height: 1.15;
}
.byline {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem 1rem;
  margin-top: 0.6rem;
  font-size: var(--fs-1);
}
.neighbors {
  margin-top: 1rem;
  padding-top: 0.6rem;
  border-top: 1px solid var(--rule);
  gap: 1rem;
}
.neighbors a {
  max-width: 48%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tools {
  border-left: 1px solid var(--rule);
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: var(--paper);
}
.tabs {
  display: flex;
  border-bottom: 1px solid var(--rule);
  padding: 0 0.25rem;
  overflow-x: auto;
  scrollbar-width: none;
}
.tabs::-webkit-scrollbar {
  display: none;
}
.tab {
  border: 0;
  border-bottom: 2px solid transparent;
  border-radius: 0;
  background: transparent;
  padding: 0.75rem 0.55rem;
  font-size: var(--fs-1);
  color: var(--ink-2);
  white-space: nowrap;
  margin-bottom: -1px;
}
.tab:hover {
  color: var(--ink);
  background: transparent;
}
.tab.on {
  color: var(--blue-2);
  border-bottom-color: var(--blue-2);
}
.count {
  margin-left: 0.3rem;
  color: var(--gold-2);
  font-size: var(--fs-0);
}
.tabpanel {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 0.9rem 1.1rem 2rem;
}
@media (max-width: 1000px) {
  .workspace {
    grid-template-columns: 1fr;
    height: auto;
  }
  .reader-col {
    padding: 1.25rem 1.25rem 2rem;
  }
  .tools {
    border-left: 0;
    border-top: 1px solid var(--rule);
  }
  .tabpanel {
    min-height: 60vh;
  }
}
</style>
