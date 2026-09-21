<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { api, type ChatBlock } from '../api'
import { useChatStore } from '../stores/chat'
import { useLessonStore } from '../stores/lesson'
import { useUiStore } from '../stores/ui'
import { useAuthStore } from '../stores/auth'
import { renderMarkdown } from '../utils/markdown'

const props = defineProps<{ talkId: string; draft?: string }>()
const chat = useChatStore()
const lesson = useLessonStore()
const ui = useUiStore()
const auth = useAuthStore()

const input = ref('')
const configured = ref<boolean | null>(null)
const providerLabel = ref('')
const list = ref<HTMLElement | null>(null)
const openTools = ref<Set<string>>(new Set())

onMounted(async () => {
  await chat.load(props.talkId)
  try {
    const s = await api.aiStatus()
    configured.value = s.configured
    providerLabel.value = s.label
  } catch {
    configured.value = false
  }
})
watch(() => props.talkId, (id) => chat.load(id))
watch(
  () => props.draft,
  (d) => {
    if (d) input.value = d
  },
  { immediate: true },
)
watch(
  () => chat.messages.map((m) => m.blocks.length + (m.blocks.at(-1)?.text?.length || 0)),
  async () => {
    await nextTick()
    list.value?.scrollTo({ top: list.value.scrollHeight })
  },
)

const suggestions = [
  'Summarize the main message of this talk in three or four points, quoting its own words.',
  'List the scriptures this talk cites and what each one adds to the message.',
  'Find other conference talks on the same topic and say how each relates.',
  'What questions could I ask the quorum to open a discussion on this talk?',
]

async function send(text?: string) {
  const t = (text ?? input.value).trim()
  if (!t || chat.streaming) return
  input.value = ''
  await chat.send(t)
}

function onKey(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    send()
  }
}

function onCiteClick(e: MouseEvent) {
  const el = (e.target as HTMLElement).closest('button.cite') as HTMLElement | null
  if (!el) return
  const kind = el.dataset.citeKind
  const value = el.dataset.citeValue || ''
  if (kind === 'talk') ui.openTalk(value)
  else if (kind === 'scripture') ui.openScripture(value)
}

function toggleTool(id: string) {
  const s = new Set(openTools.value)
  s.has(id) ? s.delete(id) : s.add(id)
  openTools.value = s
}

function pinAnswer(b: ChatBlock) {
  if (!b.text) return
  const plain = b.text.replace(/\[\[(talk|scripture):([^\]]+)\]\]/g, (_m, k, v) => (k === 'scripture' ? `(${v})` : ''))
  lesson.addPin({ kind: 'note', text: plain.trim(), note: 'From AI assistant' })
}

const sessionOptions = computed(() => chat.sessions)

function describeCall(b: ChatBlock): string {
  const input = (b.input || {}) as Record<string, unknown>
  const q = String(input.query || input.ref || input.talk_id || '')
  const verb: Record<string, string> = {
    search_talks: 'Searching talks for',
    get_talk: 'Reading talk',
    get_scripture: 'Looking up',
    talks_citing_scripture: 'Finding talks citing',
    talks_citing_talk: 'Finding citations of',
  }
  return `${verb[b.name || ''] || b.name} ${q ? `“${q}”` : ''}…`
}
</script>

<template>
  <div class="chat">
    <div v-if="configured === false" class="notice">
      <template v-if="auth.user?.is_admin">
        No AI provider is set up yet. Add an Anthropic API key or an Ollama model in
        <RouterLink to="/settings">Settings</RouterLink>.
      </template>
      <template v-else>The AI assistant is not set up yet. Ask the administrator.</template>
    </div>

    <div class="row between sessions">
      <select
        :value="chat.sessionId ?? ''"
        aria-label="Conversation"
        @change="(e) => { const v = (e.target as HTMLSelectElement).value; v ? chat.openSession(Number(v)) : chat.newSession() }"
      >
        <option value="">New conversation</option>
        <option v-for="s in sessionOptions" :key="s.id" :value="s.id">{{ s.title || 'Untitled' }} ({{ s.message_count }})</option>
      </select>
      <button v-if="chat.sessionId" class="quiet small" @click="chat.deleteSession(chat.sessionId!)">Delete</button>
      <span v-if="!chat.provider" class="faint small">{{ providerLabel }}</span>
    </div>

    <div ref="list" class="messages" @click="onCiteClick">
      <div v-if="!chat.messages.length" class="starter">
        <p class="muted">Ask about the assigned talk. The assistant can search all talks and the scriptures, and every reference it gives is clickable.</p>
        <ul>
          <li v-for="s in suggestions" :key="s"><button class="quiet" @click="send(s)">{{ s }}</button></li>
        </ul>
      </div>

      <div v-for="(m, i) in chat.messages" :key="i" class="msg" :class="m.role">
        <template v-for="(b, j) in m.blocks" :key="j">
          <div v-if="b.type === 'text'" class="bubble">
            <div class="md" v-html="renderMarkdown(b.text || '')"></div>
            <button v-if="m.role === 'assistant' && !m.streaming" class="quiet small pin" @click="pinAnswer(b)">Pin this answer</button>
          </div>
          <div v-else-if="b.type === 'tool'" class="tool">
            <button class="toolhead" @click="toggleTool(b.id || String(j))">
              <span class="dot" :class="{ busy: !b.summary }"></span>
              {{ b.summary || describeCall(b) }}
            </button>
            <div v-if="openTools.has(b.id || String(j)) && b.refs?.length" class="toolrefs">
              <template v-for="(r, k) in b.refs" :key="k">
                <button v-if="r.type === 'talk'" class="quiet small" @click="ui.openTalk(r.id!)">{{ r.title }}</button>
                <button v-else class="ref" @click="ui.openScripture(r.ref!)">{{ r.ref }}</button>
              </template>
            </div>
          </div>
          <div v-else class="notice error small">{{ b.text }}</div>
        </template>
        <span v-if="m.streaming && !m.blocks.length" class="muted small">Thinking…</span>
      </div>
    </div>

    <form class="composer" @submit.prevent="send()">
      <textarea v-model="input" rows="2" placeholder="Ask about the talk, or say what to find…" @keydown="onKey" :disabled="configured === false"></textarea>
      <div class="row">
        <button v-if="chat.streaming" type="button" @click="chat.stop()">Stop</button>
        <button v-else type="submit" class="primary" :disabled="!input.trim() || configured === false">Send</button>
      </div>
    </form>
  </div>
</template>

<style scoped>
.chat {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}
.sessions {
  margin: 0.5rem 0;
}
.sessions select {
  width: auto;
  max-width: 60%;
}
.messages {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 0.25rem 0 0.75rem;
}
.starter ul {
  list-style: none;
  padding: 0;
  margin: 0.75rem 0 0;
}
.starter li button {
  text-align: left;
  white-space: normal;
  padding: 0.35rem 0.5rem;
}
.msg {
  margin: 0.6rem 0;
}
.msg.user .bubble {
  background: var(--blue-soft);
  border-radius: var(--radius);
  padding: 0.5rem 0.75rem;
  margin-left: 2rem;
}
.msg.assistant .bubble {
  padding: 0.25rem 0;
}
.md :deep(p) {
  margin: 0 0 0.6em;
}
.md :deep(ul),
.md :deep(ol) {
  margin: 0 0 0.6em;
  padding-left: 1.3em;
}
.md :deep(li) {
  margin-bottom: 0.25em;
}
.md :deep(h1),
.md :deep(h2),
.md :deep(h3) {
  font-size: var(--fs-2);
  margin: 0.8em 0 0.3em;
}
.md :deep(blockquote) {
  margin: 0.4em 0;
  padding-left: 0.75em;
  border-left: 2px solid var(--gold);
  font-family: var(--serif);
}
.md :deep(button.cite) {
  border: 0;
  background: transparent;
  padding: 0 0.1em;
  color: var(--blue-2);
  cursor: pointer;
  font: inherit;
}
.md :deep(button.cite-talk) {
  font-size: 0.85em;
  color: var(--blue-2);
  text-decoration: underline dotted;
}
.md :deep(button.cite-scripture) {
  border-bottom: 2px solid var(--gold);
  color: var(--ink);
  border-radius: 0;
}
.md :deep(button.cite:hover) {
  background: var(--gold-soft);
}
.pin {
  margin-top: 0.1rem;
}
.tool {
  margin: 0.35rem 0;
  font-size: var(--fs-0);
}
.toolhead {
  border: 0;
  background: transparent;
  color: var(--ink-2);
  padding: 0.15rem 0;
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  text-align: left;
}
.toolhead:hover {
  background: transparent;
  color: var(--blue-2);
}
.dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--gold);
  flex-shrink: 0;
}
.dot.busy {
  animation: pulse 1s infinite alternate;
}
@keyframes pulse {
  from {
    opacity: 0.35;
  }
  to {
    opacity: 1;
  }
}
.toolrefs {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem 0.5rem;
  padding: 0.25rem 0 0.25rem 1rem;
}
.composer {
  border-top: 1px solid var(--rule);
  padding-top: 0.6rem;
  display: flex;
  gap: 0.5rem;
  align-items: flex-end;
}
.composer textarea {
  flex: 1;
}
</style>
