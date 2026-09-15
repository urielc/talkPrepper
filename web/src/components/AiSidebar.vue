<script setup lang="ts">
import { onBeforeUnmount, onMounted } from 'vue'
import { useChatStore } from '../stores/chat'
import { useUiStore } from '../stores/ui'
import ChatPanel from './ChatPanel.vue'

defineProps<{ talkId: string; draft?: string }>()
const ui = useUiStore()
const chat = useChatStore()

function onKey(e: KeyboardEvent) {
  // The scripture panel and the talk drawer stack above the sidebar; let them take Escape first.
  if (e.key === 'Escape' && ui.aiOpen && !ui.scriptureRef && !ui.drawerTalkId) ui.closeAi()
}
onMounted(() => document.addEventListener('keydown', onKey))
onBeforeUnmount(() => document.removeEventListener('keydown', onKey))
</script>

<template>
  <Transition name="slide">
    <aside v-if="ui.aiOpen" class="ai" role="dialog" aria-label="Ask AI">
      <header class="ai-head">
        <div class="grow">
          <h2>Ask AI</h2>
          <div class="talk-meta">
            {{ chat.provider ? `${chat.provider.provider} · ${chat.provider.model}` : 'Research assistant for this talk' }}
          </div>
        </div>
        <button class="quiet" @click="ui.closeAi()" aria-label="Close AI sidebar">Close</button>
      </header>
      <div class="ai-body">
        <ChatPanel :talk-id="talkId" :draft="draft" />
      </div>
    </aside>
  </Transition>
  <Transition name="fade">
    <div v-if="ui.aiOpen" class="scrim" @click="ui.closeAi()"></div>
  </Transition>
</template>

<style scoped>
.scrim {
  position: fixed;
  inset: 0;
  background: rgba(10, 18, 30, 0.25);
  z-index: 24;
}
.ai {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  width: min(var(--ai-w), 100vw);
  background: var(--paper);
  border-left: 1px solid var(--rule);
  box-shadow: var(--shadow-pop);
  z-index: 25;
  display: flex;
  flex-direction: column;
}
.ai-head {
  display: flex;
  gap: 1rem;
  align-items: flex-start;
  padding: 1rem 1.25rem 0.75rem;
  border-bottom: 1px solid var(--rule);
}
.ai-head h2 {
  font-size: var(--fs-3);
}
.ai-body {
  flex: 1;
  min-height: 0;
  padding: 0.5rem 1.25rem 1rem;
  display: flex;
  flex-direction: column;
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
