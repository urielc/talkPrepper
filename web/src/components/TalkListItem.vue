<script setup lang="ts">
import { computed } from 'vue'
import type { TalkSummary } from '../api'
import { useLessonStore } from '../stores/lesson'
import { useUiStore } from '../stores/ui'
import { safeSnippet } from '../utils/markdown'

// Boolean props default to false when omitted, so opt-in flags are named for the exception.
const props = withDefaults(
  defineProps<{
    talk: TalkSummary
    snippets?: string[]
    aside?: string
    pinnable?: boolean
    openInDrawer?: boolean
    /** Opt in to hiding the snippets and aside behind a toggle; the parent owns `expanded`. */
    collapsible?: boolean
    expanded?: boolean
  }>(),
  { pinnable: true, openInDrawer: true },
)
const emit = defineEmits<{ (e: 'open', talk: TalkSummary): void; (e: 'toggle'): void }>()

const ui = useUiStore()
const lesson = useLessonStore()

const hasExtras = computed(() => !!(props.aside || props.snippets?.length))
const showExtras = computed(() => !props.collapsible || props.expanded)

function open() {
  if (props.openInDrawer !== false) ui.openTalk(props.talk.id)
  emit('open', props.talk)
}
function pin() {
  lesson.addPin({ kind: 'talk', ref_talk_id: props.talk.id })
}
</script>

<template>
  <div class="item" :class="{ collapsible, open: collapsible && expanded }">
    <template v-if="collapsible">
      <button
        v-if="hasExtras"
        type="button"
        class="toggle"
        :aria-expanded="!!expanded"
        :aria-label="`${expanded ? 'Hide' : 'Show'} passages from ${talk.title}`"
        @click="emit('toggle')"
      >
        <span class="chev" aria-hidden="true">▾</span>
      </button>
      <span v-else class="toggle" aria-hidden="true"></span>
    </template>
    <div class="grow">
      <button class="title-btn" @click="open">{{ talk.title }}</button>
      <div class="talk-meta">
        {{ talk.speaker }}<span v-if="talk.conference">, {{ talk.conference }}</span>
        <span v-if="aside && showExtras" class="aside">{{ aside }}</span>
      </div>
      <ul v-if="showExtras && snippets && snippets.length" class="snips">
        <li v-for="(s, i) in snippets" :key="i" class="serif" v-html="safeSnippet(s)"></li>
      </ul>
    </div>
    <div class="actions">
      <button
        v-if="pinnable !== false && lesson.talkId && lesson.talkId !== talk.id"
        class="quiet small"
        :disabled="lesson.hasPin('talk', talk.id)"
        @click="pin"
      >
        {{ lesson.hasPin('talk', talk.id) ? 'Pinned' : 'Pin' }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.item {
  display: flex;
  gap: 0.75rem;
  align-items: flex-start;
}
.item.collapsible {
  gap: 0.4rem;
  /* Same device as the landing page: the bar marks an open item, and is held
     transparent when closed so opening one shifts nothing sideways. */
  border-left: 3px solid transparent;
  padding-left: 0.35rem;
}
.item.open {
  border-left-color: var(--gold);
}
.toggle {
  flex: 0 0 1.25rem;
  height: 1.5rem;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--ink-3);
  font-size: var(--fs-0);
  line-height: 1;
}
.toggle:hover {
  background: transparent;
  color: var(--blue-2);
}
.toggle .chev {
  display: inline-block;
  transition: transform 0.15s ease;
}
.toggle[aria-expanded='false'] .chev {
  transform: rotate(-90deg);
}
@media (prefers-reduced-motion: reduce) {
  .toggle .chev {
    transition: none;
  }
}
.title-btn {
  border: 0;
  background: transparent;
  padding: 0;
  text-align: left;
  font-family: var(--serif);
  font-size: var(--fs-2);
  font-weight: 600;
  color: var(--ink);
  line-height: 1.3;
}
.title-btn:hover {
  color: var(--blue-2);
  background: transparent;
}
.aside {
  margin-left: 0.6rem;
  color: var(--gold-2);
}
.snips {
  margin: 0.35rem 0 0;
  padding: 0;
  list-style: none;
  color: var(--ink-2);
  font-size: var(--fs-1);
}
.snips li + li {
  margin-top: 0.2rem;
}
.actions {
  flex-shrink: 0;
  padding-top: 0.1rem;
}
</style>
