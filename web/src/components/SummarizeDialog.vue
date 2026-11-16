<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{
  initialModifier?: string
  busy?: boolean
  error?: string | null
  /** Wording: 'create' for a new study, 'update' when changing the sources, 'regenerate' for the same ones. */
  mode: 'create' | 'update' | 'regenerate'
}>()
const emit = defineEmits<{ (e: 'submit', modifier: string): void; (e: 'close'): void }>()

const modifier = ref(props.initialModifier || '')
const title = { create: 'Summarize these sources', update: 'Update the summary', regenerate: 'Regenerate the summary' }
const go = { create: 'Summarize', update: 'Update summary', regenerate: 'Regenerate' }
</script>

<template>
  <div class="scrim" @click.self="!busy && emit('close')">
    <div class="dialog" role="dialog" :aria-label="title[mode]">
      <h3>{{ title[mode] }}</h3>
      <label>
        Instructions for the summary <span class="faint">(optional)</span>
        <textarea
          v-model="modifier"
          rows="4"
          maxlength="2000"
          placeholder="For example: focus on how this helps someone facing a loss, or keep it short for a ten minute talk."
        ></textarea>
      </label>
      <p class="faint small">
        The AI reads the full text of every queued source. Quotes are checked against the sources, and suggestions
        come only from material in the library.
      </p>
      <div v-if="error" class="notice error small">{{ error }}</div>
      <div class="row end">
        <button :disabled="busy" @click="emit('close')">Cancel</button>
        <button class="primary" :disabled="busy" @click="emit('submit', modifier)">
          {{ busy ? 'Reading the sources…' : go[mode] }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.scrim {
  position: fixed;
  inset: 0;
  background: rgba(10, 18, 30, 0.35);
  z-index: 50;
  display: grid;
  place-items: center;
}
.dialog {
  background: var(--paper);
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  box-shadow: var(--shadow-pop);
  padding: 1.25rem;
  width: min(520px, 92vw);
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}
h3 {
  font-size: var(--fs-3);
}
label {
  display: block;
  font-size: var(--fs-0);
  color: var(--ink-2);
}
label textarea {
  margin-top: 0.25rem;
  width: 100%;
}
.end {
  justify-content: flex-end;
}
</style>
