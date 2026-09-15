<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api, type TalkDetail } from '../api'
import { talkRoute } from '../router'
import { useLessonStore } from '../stores/lesson'
import { useUiStore } from '../stores/ui'
import TalkReader from './TalkReader.vue'

const ui = useUiStore()
const lesson = useLessonStore()
const router = useRouter()
const talk = ref<TalkDetail | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)

watch(
  () => ui.drawerTalkId,
  async (id) => {
    talk.value = null
    error.value = null
    if (!id) return
    loading.value = true
    try {
      talk.value = await api.talk(id)
    } catch (e: any) {
      error.value = e.message
    } finally {
      loading.value = false
    }
  },
  { immediate: true },
)

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape' && ui.drawerTalkId && !ui.scriptureRef) ui.closeDrawer()
}
onMounted(() => document.addEventListener('keydown', onKey))
onBeforeUnmount(() => document.removeEventListener('keydown', onKey))

function makeLessonTalk() {
  if (!talk.value) return
  const id = talk.value.id
  ui.closeDrawer()
  router.push(talkRoute(id))
}
function pinTalk() {
  if (talk.value) lesson.addPin({ kind: 'talk', ref_talk_id: talk.value.id })
}
</script>

<template>
  <Transition name="slide">
    <aside v-if="ui.drawerTalkId" class="drawer" role="dialog" aria-label="Talk reader">
      <header class="drawer-head">
        <div class="grow">
          <template v-if="talk">
            <h2>{{ talk.title }}</h2>
            <div class="talk-meta">
              {{ talk.speaker }}, {{ talk.conference }} <a :href="talk.url" target="_blank" rel="noopener">Source</a>
            </div>
          </template>
          <div v-else-if="loading" class="muted">Loading…</div>
          <div v-else-if="error" class="notice error">{{ error }}</div>
        </div>
        <div class="row">
          <button v-if="talk && lesson.talkId && lesson.talkId !== talk.id" class="small" :disabled="lesson.hasPin('talk', talk.id)" @click="pinTalk">
            {{ lesson.hasPin('talk', talk.id) ? 'Pinned' : 'Pin talk' }}
          </button>
          <button v-if="talk && lesson.talkId !== talk.id" class="small" @click="makeLessonTalk">Make this the lesson talk</button>
          <button class="quiet" @click="ui.closeDrawer()" aria-label="Close reader">Close</button>
        </div>
      </header>
      <div class="drawer-body">
        <TalkReader v-if="talk" :talk="talk" :scroll-to="ui.drawerParagraph" compact />
      </div>
    </aside>
  </Transition>
  <Transition name="fade">
    <div v-if="ui.drawerTalkId" class="scrim" @click="ui.closeDrawer()"></div>
  </Transition>
</template>

<style scoped>
.scrim {
  position: fixed;
  inset: 0;
  background: rgba(10, 18, 30, 0.35);
  z-index: 30;
}
.drawer {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  width: min(760px, 100vw);
  background: var(--paper);
  border-left: 1px solid var(--rule);
  box-shadow: var(--shadow-pop);
  z-index: 31;
  display: flex;
  flex-direction: column;
}
.drawer-head {
  display: flex;
  gap: 1rem;
  align-items: flex-start;
  padding: 1rem 1.5rem 0.75rem;
  border-bottom: 1px solid var(--rule);
}
.drawer-head h2 {
  font-size: var(--fs-3);
}
.drawer-body {
  overflow: auto;
  padding: 1.25rem 1.5rem 3rem;
}
.slide-enter-active,
.slide-leave-active {
  transition: transform 0.22s ease;
}
.slide-enter-from,
.slide-leave-to {
  transform: translateX(100%);
}
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
