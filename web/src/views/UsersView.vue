<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, type AdminUser } from '../api'
import { useAuthStore } from '../stores/auth'
import { useUiStore } from '../stores/ui'

const auth = useAuthStore()
const ui = useUiStore()
const users = ref<AdminUser[]>([])
const email = ref('')
const name = ref('')
const asAdmin = ref(false)
const busy = ref(false)
const error = ref<string | null>(null)
const link = ref<{ email: string; link: string; reason: string } | null>(null)

onMounted(load)

async function load() {
  users.value = await api.users()
}

async function invite() {
  busy.value = true
  error.value = null
  link.value = null
  try {
    const r = await api.inviteUser(email.value.trim(), name.value.trim(), asAdmin.value)
    if (r.emailed) ui.toast(`Invitation sent to ${r.user.email}`, 'ok')
    else link.value = { email: r.user.email, link: r.link || '', reason: r.reason || '' }
    email.value = ''
    name.value = ''
    asAdmin.value = false
    await load()
  } catch (e: any) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}

async function resend(u: AdminUser) {
  const r = await api.resendInvite(u.id)
  if (r.emailed) ui.toast(`Invitation sent to ${u.email}`, 'ok')
  else link.value = { email: u.email, link: r.link || '', reason: r.reason || '' }
  await load()
}

async function toggle(u: AdminUser, field: 'disabled' | 'is_admin') {
  try {
    users.value = await api.patchUser(u.id, { [field]: !u[field] })
  } catch (e: any) {
    ui.toast(e.message, 'error')
  }
}

function copyLink() {
  if (link.value) navigator.clipboard?.writeText(link.value.link).then(() => ui.toast('Link copied', 'ok', 1500))
}
</script>

<template>
  <div class="users">
    <h1>Users</h1>
    <p class="muted">Accounts are by invitation. Each person gets a link to choose their own password.</p>

    <form class="invite" @submit.prevent="invite">
      <input v-model="email" type="email" placeholder="email@example.com" required />
      <input v-model="name" type="text" placeholder="Name (optional)" />
      <label class="row small muted"><input v-model="asAdmin" type="checkbox" /> Administrator</label>
      <button class="primary" type="submit" :disabled="busy">Invite</button>
    </form>
    <div v-if="error" class="notice error small">{{ error }}</div>
    <div v-if="link" class="notice">
      Email is not set up ({{ link.reason }}), so send this link to {{ link.email }} yourself. It is valid for three days.
      <div class="row linkrow">
        <input type="text" :value="link.link" readonly @focus="($event.target as HTMLInputElement).select()" />
        <button class="small" @click="copyLink">Copy</button>
      </div>
    </div>

    <table>
      <thead>
        <tr><th>Email</th><th>Name</th><th>Status</th><th>Last sign-in</th><th></th></tr>
      </thead>
      <tbody>
        <tr v-for="u in users" :key="u.id" :class="{ off: u.disabled }">
          <td>{{ u.email }}<span v-if="u.is_admin" class="badge">admin</span></td>
          <td>{{ u.name }}</td>
          <td>
            <template v-if="u.disabled">Disabled</template>
            <template v-else-if="!u.has_password">{{ u.invite_pending ? 'Invited' : 'Invite expired' }}</template>
            <template v-else>Active</template>
          </td>
          <td class="muted small">{{ u.last_login_at ? u.last_login_at.slice(0, 10) : '—' }}</td>
          <td class="row actions">
            <button v-if="!u.has_password || !u.invite_pending" class="quiet small" @click="resend(u)">
              {{ u.has_password ? 'Send reset link' : 'Resend invite' }}
            </button>
            <button v-if="u.id !== auth.user?.id" class="quiet small" @click="toggle(u, 'is_admin')">
              {{ u.is_admin ? 'Remove admin' : 'Make admin' }}
            </button>
            <button v-if="u.id !== auth.user?.id" class="quiet small" @click="toggle(u, 'disabled')">
              {{ u.disabled ? 'Enable' : 'Disable' }}
            </button>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.users {
  max-width: 900px;
  margin: 0 auto;
  padding: 2rem 1.25rem 4rem;
}
h1 {
  font-size: var(--fs-5);
  margin-bottom: 0.4rem;
}
.invite {
  display: grid;
  grid-template-columns: 2fr 1.5fr auto auto;
  gap: 0.6rem;
  align-items: center;
  margin: 1.25rem 0 0.75rem;
}
@media (max-width: 700px) {
  .invite {
    grid-template-columns: 1fr;
  }
}
.linkrow {
  margin-top: 0.5rem;
}
table {
  width: 100%;
  border-collapse: collapse;
  margin-top: 1.25rem;
}
th,
td {
  text-align: left;
  padding: 0.55rem 0.4rem;
  border-bottom: 1px solid var(--rule);
  vertical-align: top;
}
th {
  font-size: var(--fs-0);
  color: var(--ink-2);
  font-weight: 600;
}
tr.off td {
  color: var(--ink-3);
}
.badge {
  margin-left: 0.5rem;
  color: var(--gold-2);
  font-size: var(--fs-0);
}
.actions {
  flex-wrap: wrap;
  justify-content: flex-end;
}
</style>
