import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api, streamChat, type ChatBlock, type ChatMessage, type ChatSession } from '../api'

export const useChatStore = defineStore('chat', () => {
  const talkId = ref<string | null>(null)
  const sessions = ref<ChatSession[]>([])
  const sessionId = ref<number | null>(null)
  const messages = ref<ChatMessage[]>([])
  const streaming = ref(false)
  const error = ref<string | null>(null)
  const provider = ref<{ provider: string; model: string } | null>(null)
  let controller: AbortController | null = null

  async function load(id: string) {
    if (talkId.value !== id) {
      talkId.value = id
      sessionId.value = null
      messages.value = []
      error.value = null
    }
    sessions.value = await api.chatSessions(id)
  }

  async function openSession(id: number) {
    const s = await api.chatSession(id)
    sessionId.value = s.id
    messages.value = s.messages || []
    provider.value = { provider: s.provider, model: s.model }
  }

  function newSession() {
    sessionId.value = null
    messages.value = []
    error.value = null
  }

  async function deleteSession(id: number) {
    await api.deleteSession(id)
    if (sessionId.value === id) newSession()
    if (talkId.value) sessions.value = await api.chatSessions(talkId.value)
  }

  async function send(text: string) {
    if (!talkId.value || streaming.value) return
    error.value = null
    messages.value.push({ role: 'user', blocks: [{ type: 'text', text }] })
    const reply: ChatMessage = { role: 'assistant', blocks: [], streaming: true }
    messages.value.push(reply)
    streaming.value = true
    controller = new AbortController()
    const pending = new Map<string, ChatBlock>()

    const appendText = (t: string) => {
      const last = reply.blocks[reply.blocks.length - 1]
      if (last && last.type === 'text') last.text = (last.text || '') + t
      else reply.blocks.push({ type: 'text', text: t })
    }

    try {
      await streamChat(
        { talk_id: talkId.value, message: text, session_id: sessionId.value },
        (event, data) => {
          switch (event) {
            case 'start':
              sessionId.value = data.session_id
              provider.value = { provider: data.provider, model: data.model }
              break
            case 'text_delta':
              appendText(data.text)
              break
            case 'tool_call': {
              const b: ChatBlock = { type: 'tool', id: data.id, name: data.name, input: data.input }
              pending.set(data.id, b)
              reply.blocks.push(b)
              break
            }
            case 'tool_result': {
              const b = pending.get(data.id)
              if (b) {
                b.summary = data.summary
                b.refs = data.refs
                b.preview = data.preview
                pending.delete(data.id)
              } else {
                reply.blocks.push({ type: 'tool', id: data.id, name: data.name, summary: data.summary, refs: data.refs, preview: data.preview })
              }
              break
            }
            case 'error':
              error.value = data.message
              reply.blocks.push({ type: 'error', text: data.message })
              break
            case 'done':
              reply.id = data.message_id
              break
          }
        },
        controller.signal,
      )
    } catch (e: any) {
      if (e.name !== 'AbortError') {
        error.value = e.message || String(e)
        reply.blocks.push({ type: 'error', text: error.value! })
      }
    } finally {
      reply.streaming = false
      streaming.value = false
      controller = null
      if (talkId.value) sessions.value = await api.chatSessions(talkId.value)
    }
  }

  function stop() {
    controller?.abort()
  }

  return { talkId, sessions, sessionId, messages, streaming, error, provider, load, openSession, newSession, deleteSession, send, stop }
})
