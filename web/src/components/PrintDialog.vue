<script setup lang="ts">
import { computed, ref } from 'vue'
import { api } from '../api'

const props = defineProps<{ talkId: string }>()
const emit = defineEmits<{ (e: 'close'): void }>()

const options = [
  { key: 'notes', label: 'Notes', hint: 'Your lesson notes' },
  { key: 'essence', label: 'Essence', hint: 'The talk’s central message' },
  { key: 'points', label: 'Main points', hint: 'Observations in the talk’s order' },
  { key: 'quotes', label: 'Worth reading aloud', hint: 'Verbatim quotations from the talk' },
  { key: 'questions', label: 'Questions for the quorum', hint: 'Opening, discussion and application questions' },
  { key: 'pins', label: 'Pinned references', hint: 'Talks, passages and quotes you pinned' },
]

const selected = ref<Set<string>>(new Set(options.map((o) => o.key)))
try {
  const saved = localStorage.getItem('lp.printSections')
  if (saved) {
    const keys = JSON.parse(saved) as string[]
    if (Array.isArray(keys) && keys.length) selected.value = new Set(keys.filter((k) => options.some((o) => o.key === k)))
  }
} catch {
  /* ignore */
}

function toggle(key: string) {
  const s = new Set(selected.value)
  s.has(key) ? s.delete(key) : s.add(key)
  selected.value = s
}
const none = computed(() => selected.value.size === 0)

function print() {
  const keys = options.map((o) => o.key).filter((k) => selected.value.has(k))
  try {
    localStorage.setItem('lp.printSections', JSON.stringify(keys))
  } catch {
    /* ignore */
  }
  window.open(api.exportUrl(props.talkId, keys), '_blank', 'noopener')
  emit('close')
}
</script>

<template>
  <div class="scrim" @click.self="emit('close')">
    <div class="dialog" role="dialog" aria-label="Choose what to print">
      <h3>What to print</h3>
      <ul class="opts">
        <li v-for="o in options" :key="o.key">
          <label>
            <input type="checkbox" :checked="selected.has(o.key)" @change="toggle(o.key)" />
            <span class="lbl">{{ o.label }}</span>
            <span class="hint muted small">{{ o.hint }}</span>
          </label>
        </li>
      </ul>
      <p class="faint small">Opens the print page in a new tab. Digest sections appear only once a digest has been generated.</p>
      <div class="row end">
        <button @click="emit('close')">Cancel</button>
        <button class="primary" :disabled="none" @click="print">Print</button>
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
  width: min(440px, 92vw);
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}
h3 {
  font-size: var(--fs-3);
}
.opts {
  list-style: none;
  margin: 0;
  padding: 0;
}
.opts li + li {
  border-top: 1px solid var(--rule);
}
.opts label {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 0.15rem 0.6rem;
  align-items: center;
  padding: 0.5rem 0;
  cursor: pointer;
}
.opts input {
  grid-row: span 2;
}
.lbl {
  font-weight: 600;
}
.hint {
  grid-column: 2;
}
.end {
  justify-content: flex-end;
}
</style>
