import { defineStore } from 'pinia'
import { ref } from 'vue'
import { AUDIENCE_LABELS, type AudienceKey, type SourceItem, type Study } from '../api'

export const MAX_SOURCES = 12
const KEY = 'lp.topicQueue'

/** The topic page's audience and queue of sources. Kept in localStorage until a study is created. */
export const useTopicStore = defineStore('topic', () => {
  const audience = ref<AudienceKey>('adults-male')
  const queue = ref<SourceItem[]>([])
  /** Set while changing the sources of an existing study: Summarize then updates that study. */
  const editing = ref<{ id: number; topic: string; modifier: string } | null>(null)
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) || 'null')
    if (saved && saved.audience in AUDIENCE_LABELS) audience.value = saved.audience
    if (saved && Array.isArray(saved.queue)) queue.value = saved.queue.slice(0, MAX_SOURCES)
    if (saved?.editing && typeof saved.editing.id === 'number') editing.value = saved.editing
  } catch {
    /* storage unavailable */
  }

  function persist() {
    try {
      localStorage.setItem(KEY, JSON.stringify({ audience: audience.value, queue: queue.value, editing: editing.value }))
    } catch {
      /* ignore */
    }
  }

  function setAudience(a: AudienceKey) {
    audience.value = a
    persist()
  }
  function has(kind: string, ref: string): boolean {
    return queue.value.some((s) => s.kind === kind && s.ref === ref)
  }
  /** Returns false when the queue is full. */
  function add(item: SourceItem): boolean {
    if (has(item.kind, item.ref)) return true
    if (queue.value.length >= MAX_SOURCES) return false
    queue.value = [...queue.value, { kind: item.kind, ref: item.ref, title: item.title }]
    persist()
    return true
  }
  function remove(index: number) {
    queue.value = queue.value.filter((_, i) => i !== index)
    persist()
  }
  function move(index: number, delta: number) {
    const j = index + delta
    if (j < 0 || j >= queue.value.length) return
    const q = [...queue.value]
    ;[q[index], q[j]] = [q[j], q[index]]
    queue.value = q
    persist()
  }
  function clear() {
    queue.value = []
    persist()
  }
  /** Load a study's sources into the queue to add to or remove from them. */
  function edit(study: Study) {
    audience.value = study.audience
    queue.value = study.sources.slice(0, MAX_SOURCES)
    editing.value = { id: study.id, topic: study.topic, modifier: study.modifier }
    persist()
  }
  function stopEditing() {
    editing.value = null
    persist()
  }

  return { audience, queue, editing, setAudience, has, add, remove, move, clear, edit, stopEditing }
})
