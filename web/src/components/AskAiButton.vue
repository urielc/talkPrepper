<script setup lang="ts">
import { useChatStore } from '../stores/chat'
import { useUiStore } from '../stores/ui'

const ui = useUiStore()
const chat = useChatStore()
</script>

<template>
  <button v-if="!ui.aiOpen" class="ask-pill" @click="ui.openAi()" aria-label="Open the AI assistant">
    <span class="dot" :class="{ busy: chat.streaming }"></span>
    Ask AI
  </button>
</template>

<style scoped>
.ask-pill {
  position: fixed;
  right: 1.25rem;
  bottom: 1.25rem;
  z-index: 22;
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.6rem 1rem;
  border-radius: 999px;
  border: 1px solid var(--blue);
  background: var(--blue);
  color: #fff;
  font-weight: 600;
  box-shadow: var(--shadow-pop);
}
.ask-pill:hover {
  filter: brightness(1.1);
}
.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--gold);
}
.dot.busy {
  animation: pulse 0.9s infinite alternate;
}
@keyframes pulse {
  from {
    opacity: 0.3;
  }
  to {
    opacity: 1;
  }
}
@media print {
  .ask-pill {
    display: none;
  }
}
</style>
