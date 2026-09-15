<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { api } from '../api'
import { useUiStore } from '../stores/ui'

const props = defineProps<{ talkId: string }>()
const emit = defineEmits<{ (e: 'close'): void }>()
const ui = useUiStore()

const to = ref('')
const subject = ref('')
const ready = ref<boolean | null>(null)
const missing = ref('')
const sending = ref(false)
const error = ref<string | null>(null)

onMounted(async () => {
  try {
    const s = await api.settings()
    ready.value = Boolean(s.email_ready)
    missing.value = String(s.email_missing || '')
    try {
      to.value = localStorage.getItem('lp.lastEmailTo') || ''
    } catch {
      /* ignore */
    }
  } catch {
    ready.value = false
  }
})

async function send() {
  const list = to.value
    .split(/[,;\s]+/)
    .map((s) => s.trim())
    .filter(Boolean)
  if (!list.length) {
    error.value = 'Enter at least one email address.'
    return
  }
  sending.value = true
  error.value = null
  try {
    const r = await api.emailLesson(props.talkId, list, subject.value || undefined)
    try {
      localStorage.setItem('lp.lastEmailTo', to.value)
    } catch {
      /* ignore */
    }
    ui.toast(`Sent to ${r.to.join(', ')}`, 'ok')
    emit('close')
  } catch (e: any) {
    error.value = e.message
  } finally {
    sending.value = false
  }
}
</script>

<template>
  <div class="scrim" @click.self="emit('close')">
    <div class="dialog" role="dialog" aria-label="Email lesson notes">
      <h3>Email notes and pins</h3>
      <div v-if="ready === false" class="notice">
        Email is not set up. {{ missing }} Go to <RouterLink to="/settings">Settings</RouterLink>.
      </div>
      <template v-else>
        <label>
          To
          <input v-model="to" type="text" placeholder="you@example.com, someone@example.com" autofocus />
        </label>
        <label>
          Subject <span class="faint">(optional)</span>
          <input v-model="subject" type="text" placeholder="Lesson prep: talk title" />
        </label>
        <div v-if="error" class="notice error small">{{ error }}</div>
      </template>
      <div class="row end">
        <button @click="emit('close')">Cancel</button>
        <button v-if="ready" class="primary" :disabled="sending" @click="send">{{ sending ? 'Sending…' : 'Send' }}</button>
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
  width: min(480px, 92vw);
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
label input {
  margin-top: 0.25rem;
}
.end {
  justify-content: flex-end;
}
</style>
