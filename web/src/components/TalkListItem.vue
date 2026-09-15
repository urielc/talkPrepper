<script setup lang="ts">
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
  }>(),
  { pinnable: true, openInDrawer: true },
)
const emit = defineEmits<{ (e: 'open', talk: TalkSummary): void }>()

const ui = useUiStore()
const lesson = useLessonStore()

function open() {
  if (props.openInDrawer !== false) ui.openTalk(props.talk.id)
  emit('open', props.talk)
}
function pin() {
  lesson.addPin({ kind: 'talk', ref_talk_id: props.talk.id })
}
</script>

<template>
  <div class="item">
    <div class="grow">
      <button class="title-btn" @click="open">{{ talk.title }}</button>
      <div class="talk-meta">
        {{ talk.speaker }}<span v-if="talk.conference">, {{ talk.conference }}</span>
        <span v-if="aside" class="aside">{{ aside }}</span>
      </div>
      <ul v-if="snippets && snippets.length" class="snips">
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
