<script setup lang="ts">
import { AUDIENCE_LABELS, type AudienceKey } from '../api'

defineProps<{ modelValue: AudienceKey; title?: string }>()
const emit = defineEmits<{ (e: 'change', key: AudienceKey): void }>()

const options = Object.entries(AUDIENCE_LABELS) as [AudienceKey, string][]
</script>

<template>
  <label class="class-pick small">
    <span class="muted">Class</span>
    <select
      :value="modelValue"
      aria-label="Who this lesson is for"
      :title="title ?? 'The questions and Ask AI are written for this audience'"
      @change="emit('change', ($event.target as HTMLSelectElement).value as AudienceKey)"
    >
      <option v-for="[k, l] in options" :key="k" :value="k">{{ l }}</option>
    </select>
  </label>
</template>

<style scoped>
.class-pick {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
}
.class-pick select {
  width: auto;
  padding-top: 0.2rem;
  padding-bottom: 0.2rem;
}
</style>
