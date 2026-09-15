<script setup lang="ts">
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { api, type IndexStatus } from '../api'
import { useUiStore } from '../stores/ui'

const ui = useUiStore()
const s = reactive<Record<string, string>>({})
const flags = reactive<Record<string, boolean>>({})
const loaded = ref(false)
const saving = ref(false)
const aiResult = ref<string | null>(null)
const aiError = ref<string | null>(null)
const ollamaModels = ref<string[]>([])
const emailTo = ref('')
const emailResult = ref<string | null>(null)
const index = ref<IndexStatus | null>(null)
let poll: ReturnType<typeof setInterval> | null = null

const anthropicModels = ['claude-opus-5', 'claude-sonnet-5', 'claude-haiku-4-5']

onMounted(async () => {
  const data = await api.settings()
  for (const [k, v] of Object.entries(data)) {
    if (typeof v === 'boolean') flags[k] = v
    else s[k] = String(v)
  }
  loaded.value = true
  await refreshIndex()
})
onBeforeUnmount(() => poll && clearInterval(poll))

async function save(keys?: string[]) {
  saving.value = true
  try {
    const values: Record<string, string> = {}
    for (const k of keys ?? Object.keys(s)) values[k] = s[k]
    const data = await api.saveSettings(values)
    for (const [k, v] of Object.entries(data)) {
      if (typeof v === 'boolean') flags[k] = v
      else s[k] = String(v)
    }
    ui.toast('Settings saved', 'ok', 1500)
  } catch (e: any) {
    ui.toast(e.message, 'error')
  } finally {
    saving.value = false
  }
}

async function testAi() {
  aiResult.value = null
  aiError.value = null
  await save()
  try {
    const r = await api.testAi()
    aiResult.value = `Connected: ${r.display_name || r.model}`
  } catch (e: any) {
    aiError.value = e.message
  }
}

async function loadOllama() {
  await save(['ollama_base_url'])
  try {
    ollamaModels.value = (await api.ollamaModels()).models
    if (!ollamaModels.value.length) aiError.value = 'Ollama is reachable but has no models pulled.'
  } catch (e: any) {
    aiError.value = e.message
  }
}

async function testEmail() {
  emailResult.value = null
  await save()
  try {
    await api.testEmail(emailTo.value)
    emailResult.value = `Test email sent to ${emailTo.value}`
  } catch (e: any) {
    emailResult.value = e.message
  }
}

async function refreshIndex() {
  index.value = await api.indexStatus()
  if (index.value.job?.running && !poll) poll = setInterval(refreshIndex, 1500)
  if (!index.value.job?.running && poll) {
    clearInterval(poll)
    poll = null
  }
}
async function rebuild(skip = false) {
  try {
    await api.rebuildIndex(skip)
    await refreshIndex()
  } catch (e: any) {
    ui.toast(e.message, 'error')
  }
}
</script>

<template>
  <div class="settings" v-if="loaded">
    <h1>Settings</h1>

    <section>
      <h2>AI assistant</h2>
      <p class="muted">Both providers use the same tools to search the talks and scriptures. Keys are stored in the app database on this machine.</p>
      <div class="choice">
        <label><input v-model="s.ai_provider" type="radio" value="anthropic" /> Claude (Anthropic API)</label>
        <label><input v-model="s.ai_provider" type="radio" value="ollama" /> Ollama (local model)</label>
      </div>

      <div v-if="s.ai_provider === 'anthropic'" class="fields">
        <label>
          API key
          <input v-model="s.anthropic_api_key" type="password" autocomplete="off" :placeholder="flags.anthropic_api_key_set ? 'Saved (enter a new key to replace)' : 'sk-ant-…'" />
        </label>
        <label>
          Model
          <select v-model="s.anthropic_model">
            <option v-for="m in anthropicModels" :key="m" :value="m">{{ m }}</option>
            <option v-if="!anthropicModels.includes(s.anthropic_model)" :value="s.anthropic_model">{{ s.anthropic_model }}</option>
          </select>
        </label>
        <p class="faint small">
          Requests use adaptive thinking and prompt caching for the talk text. Refusal fallbacks are enabled so a declined request is retried on another Claude model automatically.
        </p>
      </div>

      <div v-else class="fields">
        <label>
          Ollama URL
          <input v-model="s.ollama_base_url" type="url" />
        </label>
        <label>
          Model
          <div class="row">
            <select v-if="ollamaModels.length" v-model="s.ollama_model">
              <option v-for="m in ollamaModels" :key="m" :value="m">{{ m }}</option>
            </select>
            <input v-else v-model="s.ollama_model" type="text" placeholder="e.g. llama3.1:8b" />
            <button type="button" @click="loadOllama">List models</button>
          </div>
        </label>
        <p class="faint small">Tool calling needs a model that supports it (llama3.1, qwen2.5, mistral-nemo…). Other models get search results injected instead.</p>
      </div>

      <div class="row">
        <button class="primary" :disabled="saving" @click="save()">Save</button>
        <button :disabled="saving" @click="testAi">Save and test</button>
        <span v-if="aiResult" class="ok-text">{{ aiResult }}</span>
      </div>
      <div v-if="aiError" class="notice error small">{{ aiError }}</div>
    </section>

    <section>
      <h2>Email</h2>
      <p class="muted">Used by “Email…” on the Notes & pins tab to send your notes and pinned references.</p>
      <div class="choice">
        <label><input v-model="s.email_provider" type="radio" value="postmark" /> Postmark</label>
        <label><input v-model="s.email_provider" type="radio" value="smtp" /> SMTP server</label>
      </div>
      <div class="fields">
        <label>
          From address
          <input v-model="s.email_from" type="email" placeholder="you@yourdomain.com" />
          <span class="faint small">Must be a verified sender signature or domain in Postmark.</span>
        </label>
        <template v-if="s.email_provider === 'postmark'">
          <label>
            Postmark server token
            <input v-model="s.postmark_server_token" type="password" autocomplete="off" :placeholder="flags.postmark_server_token_set ? 'Saved (enter a new token to replace)' : ''" />
          </label>
        </template>
        <template v-else>
          <div class="two">
            <label>Host <input v-model="s.smtp_host" type="text" placeholder="smtp.postmarkapp.com" /></label>
            <label>Port <input v-model="s.smtp_port" type="number" /></label>
          </div>
          <div class="two">
            <label>Username <input v-model="s.smtp_user" type="text" autocomplete="off" /></label>
            <label>Password <input v-model="s.smtp_password" type="password" autocomplete="off" :placeholder="flags.smtp_password_set ? 'Saved' : ''" /></label>
          </div>
          <label>
            Encryption
            <select v-model="s.smtp_tls">
              <option value="starttls">STARTTLS (port 587)</option>
              <option value="ssl">SSL/TLS (port 465)</option>
              <option value="none">None</option>
            </select>
          </label>
        </template>
      </div>
      <div class="row wrap">
        <button class="primary" :disabled="saving" @click="save()">Save</button>
        <input v-model="emailTo" type="email" placeholder="Send a test to…" class="test-to" />
        <button :disabled="!emailTo" @click="testEmail">Send test</button>
      </div>
      <div v-if="emailResult" class="notice small" :class="{ ok: emailResult.startsWith('Test email sent') }">{{ emailResult }}</div>
    </section>

    <section>
      <h2>Talk index</h2>
      <template v-if="index">
        <dl class="status">
          <dt>Built</dt>
          <dd>{{ index.built_at || 'never' }}</dd>
          <dt>Talks</dt>
          <dd>{{ index.stats?.talks ?? '—' }} in {{ index.stats?.conferences ?? '—' }} conferences</dd>
          <dt>Scripture references</dt>
          <dd>{{ index.stats?.scripture_refs ?? '—' }}</dd>
          <dt>Talk citations resolved</dt>
          <dd>{{ index.stats?.talk_refs_resolved ?? '—' }} of {{ index.stats?.talk_refs ?? '—' }}</dd>
          <dt>Embeddings</dt>
          <dd>{{ index.embeddings_exist ? `${index.stats?.chunks ?? ''} chunks (${index.embedding_model})` : 'not built' }}</dd>
          <dt>Source file</dt>
          <dd>{{ index.talks_json_exists ? `data/general_conference_talks.json, updated ${index.talks_json_mtime}` : 'missing' }}</dd>
        </dl>
        <div v-if="index.job?.running" class="notice">
          Rebuilding: {{ index.job.stage }}
          <template v-if="index.job.total"> {{ index.job.done }} / {{ index.job.total }}</template>
        </div>
        <div v-else-if="index.job?.error" class="notice error">Last rebuild failed: {{ index.job.error }}</div>
        <div v-else-if="index.job?.finished_at" class="notice ok">Rebuilt {{ index.job.finished_at }}</div>
        <div class="row">
          <button :disabled="index.job?.running" @click="rebuild(false)">Rebuild index</button>
          <button class="quiet" :disabled="index.job?.running" @click="rebuild(true)">Rebuild without embeddings</button>
        </div>
        <p class="faint small">Rebuild after re-running the scraper. Embeddings are reused for unchanged text, so a rebuild is usually quick.</p>
      </template>
    </section>

    <section>
      <h2>Appearance</h2>
      <div class="choice">
        <label><input :checked="ui.theme === 'system'" type="radio" @change="ui.setTheme('system')" /> Match system</label>
        <label><input :checked="ui.theme === 'light'" type="radio" @change="ui.setTheme('light')" /> Light</label>
        <label><input :checked="ui.theme === 'dark'" type="radio" @change="ui.setTheme('dark')" /> Dark</label>
      </div>
    </section>
  </div>
</template>

<style scoped>
.settings {
  max-width: 720px;
  margin: 0 auto;
  padding: 2rem 1.25rem 4rem;
}
h1 {
  font-size: var(--fs-5);
  margin-bottom: 1rem;
}
section {
  padding: 1.5rem 0;
  border-top: 1px solid var(--rule);
}
h2 {
  font-size: var(--fs-3);
  margin-bottom: 0.4rem;
}
.choice {
  display: flex;
  gap: 1.25rem;
  margin: 0.75rem 0;
}
.fields {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  margin-bottom: 1rem;
}
.fields label {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  font-size: var(--fs-0);
  color: var(--ink-2);
}
.two {
  display: grid;
  grid-template-columns: 2fr 1fr;
  gap: 0.75rem;
}
.test-to {
  width: 16rem;
}
.ok-text {
  color: var(--ok);
}
.status {
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: 0.25rem 1rem;
  margin: 0.5rem 0 1rem;
}
.status dt {
  color: var(--ink-2);
}
.status dd {
  margin: 0;
}
</style>
