<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const token = computed(() => (typeof route.query.token === 'string' ? route.query.token : ''))
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
    error.value = 'The two passwords do not match.'
    return
  }
  busy.value = true
  try {
    await auth.setPassword(token.value, password.value)
    router.replace('/')
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
      <h1>Choose a password</h1>
      <div v-if="!token" class="notice error">This link is missing its token. Ask for a new invitation.</div>
      <template v-else>
        <p class="muted">At least 10 characters. A short phrase works well.</p>
        <label>
          New password
          <input v-model="password" type="password" autocomplete="new-password" required autofocus />
        </label>
        <label>
          Repeat it
          <input v-model="confirm" type="password" autocomplete="new-password" required />
        </label>
        <div v-if="error" class="notice error small">{{ error }}</div>
        <button class="primary" type="submit" :disabled="busy">{{ busy ? '…' : 'Save and sign in' }}</button>
      </template>
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
