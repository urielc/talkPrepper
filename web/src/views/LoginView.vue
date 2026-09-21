<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const email = ref('')
const password = ref('')
const busy = ref(false)
const error = ref<string | null>(null)
const forgotMode = ref(false)
const forgotSent = ref(false)

async function submit() {
  busy.value = true
  error.value = null
  try {
    if (forgotMode.value) {
      await api.forgot(email.value.trim())
      forgotSent.value = true
    } else {
      await auth.login(email.value.trim(), password.value)
      const next = typeof route.query.next === 'string' && /^\/(?!\/)/.test(route.query.next) ? route.query.next : '/'
      router.replace(next)
    }
  } catch (e: any) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="login-wrap">
    <form class="card" @submit.prevent="submit">
      <img src="/mark.svg" alt="" width="40" height="40" />
      <h1>Lesson Prep</h1>
      <p class="muted">A preparation tool for lessons built on General Conference talks.</p>

      <template v-if="forgotSent">
        <div class="notice ok">If that address has an account, a reset link is on its way. It is valid for two hours.</div>
        <button type="button" class="quiet" @click="forgotMode = false; forgotSent = false">Back to sign in</button>
      </template>
      <template v-else>
        <label>
          Email
          <input v-model="email" type="email" autocomplete="username" required autofocus />
        </label>
        <label v-if="!forgotMode">
          Password
          <input v-model="password" type="password" autocomplete="current-password" required />
        </label>
        <div v-if="error" class="notice error small">{{ error }}</div>
        <button class="primary" type="submit" :disabled="busy">
          {{ busy ? '…' : forgotMode ? 'Send reset link' : 'Sign in' }}
        </button>
        <button type="button" class="quiet small" @click="forgotMode = !forgotMode; error = null">
          {{ forgotMode ? 'Back to sign in' : 'Forgot your password?' }}
        </button>
      </template>
      <p class="faint small">Accounts are by invitation. Ask the administrator if you need one.</p>
    </form>
  </div>
</template>

<style scoped>
.login-wrap {
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
