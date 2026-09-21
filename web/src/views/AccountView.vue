<script setup lang="ts">
import { ref } from 'vue'
import { api } from '../api'
import { useAuthStore } from '../stores/auth'
import { useUiStore } from '../stores/ui'

const auth = useAuthStore()
const ui = useUiStore()

const current = ref('')
const password = ref('')
const confirm = ref('')
const busy = ref(false)
const error = ref<string | null>(null)

async function submit() {
  error.value = null
  if (password.value.length < 10) {
    error.value = 'Use at least 10 characters.'
    return
  }
  if (password.value !== confirm.value) {
    error.value = 'The two new passwords do not match.'
    return
  }
  busy.value = true
  try {
    await api.changePassword(current.value, password.value)
    current.value = password.value = confirm.value = ''
    ui.toast('Password changed. Other devices were signed out.', 'ok', 4000)
  } catch (e: any) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="wrap">
    <form class="card" @submit.prevent="submit">
      <h1>Change password</h1>
      <p class="muted">Signed in as {{ auth.user?.email }}. Saving a new password signs out every other device.</p>
      <label>
        Current password
        <input v-model="current" type="password" autocomplete="current-password" required autofocus />
      </label>
      <label>
        New password
        <input v-model="password" type="password" autocomplete="new-password" required />
      </label>
      <label>
        Repeat the new password
        <input v-model="confirm" type="password" autocomplete="new-password" required />
      </label>
      <p class="muted small">At least 10 characters. A short phrase works well.</p>
      <div v-if="error" class="notice error small">{{ error }}</div>
      <button class="primary" type="submit" :disabled="busy">{{ busy ? '…' : 'Save new password' }}</button>
    </form>
  </div>
</template>

<style scoped>
.wrap {
  min-height: calc(100vh - var(--header-h));
  display: grid;
  place-items: start center;
  padding: 4rem 1.25rem;
}
.card {
  width: min(400px, 100%);
  display: flex;
  flex-direction: column;
  gap: 0.9rem;
  padding: 1.75rem;
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: var(--paper);
}
h1 {
  font-size: var(--fs-4);
}
label {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  font-size: var(--fs-0);
  color: var(--ink-2);
}
</style>
