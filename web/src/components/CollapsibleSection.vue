<script setup lang="ts">
import { ref, watch } from 'vue'

const props = withDefaults(
  defineProps<{
    title: string
    count?: number | null
    storageKey?: string
    defaultOpen?: boolean
  }>(),
  { count: null, storageKey: '', defaultOpen: true },
)

const open = ref(props.defaultOpen)
if (props.storageKey) {
  try {
    const saved = localStorage.getItem(`lp.section.${props.storageKey}`)
    if (saved === '0' || saved === '1') open.value = saved === '1'
  } catch {
    /* storage unavailable */
  }
}
watch(open, (v) => {
  if (!props.storageKey) return
  try {
    localStorage.setItem(`lp.section.${props.storageKey}`, v ? '1' : '0')
  } catch {
    /* ignore */
  }
})
</script>

<template>
  <section class="csec">
    <div class="head-row">
      <button class="section-head" :aria-expanded="open" @click="open = !open">
        <span class="title">{{ title }}</span>
        <span v-if="count != null" class="count">{{ count }}</span>
        <span class="chev" aria-hidden="true">▾</span>
      </button>
      <div v-if="$slots.actions" class="actions"><slot name="actions" /></div>
    </div>
    <div v-show="open" class="body">
      <slot />
    </div>
  </section>
</template>

<style scoped>
.csec {
  margin-bottom: 1rem;
}
.head-row {
  display: flex;
  align-items: center;
  border-bottom: 1px solid var(--rule);
}
.head-row .section-head {
  border-bottom: 0;
}
.actions {
  flex-shrink: 0;
  padding-left: 0.5rem;
}
.body {
  padding-top: 0.5rem;
}
</style>
